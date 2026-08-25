import os

os.environ.setdefault('SECRET_KEY','integration-test-secret')

import psycopg2
from psycopg2.extras import RealDictCursor

import app as app_module
from migration_runner import run_migrations

DATABASE_URL=os.environ['DATABASE_URL']


def conn():
    return psycopg2.connect(DATABASE_URL,cursor_factory=RealDictCursor)


def scalar(sql,params=()):
    c=conn()
    try:
        with c.cursor() as cur:
            cur.execute(sql,params);row=cur.fetchone();return next(iter(row.values())) if row else None
    finally:c.close()


def main():
    app_module.ensure_schema()
    run_migrations()

    import wsgi  # noqa: F401
    flask_app=app_module.app
    flask_app.config.update(TESTING=True,SECRET_KEY='integration-test-secret')

    c=conn()
    try:
        with c.cursor() as cur:
            cur.execute("INSERT INTO users(username,full_name,password_hash) VALUES('tester','Integration Tester','x') RETURNING id")
            user_id=cur.fetchone()['id']
            cur.execute("INSERT INTO filaments(material,color,remaining_g,purchase_cost,spool_weight_g) VALUES('PLA','Branco',1000,20,1000) RETURNING id")
            filament_id=cur.fetchone()['id']
            cur.execute("INSERT INTO filaments(material,color,remaining_g,purchase_cost,spool_weight_g) VALUES('PLA','Preto',500,20,1000) RETURNING id")
            black_id=cur.fetchone()['id']
            cur.execute("INSERT INTO machines(name,status) VALUES('X1C Test','available') RETURNING id")
            machine_id=cur.fetchone()['id']
            cur.execute("""INSERT INTO products(sku,name,description,stock_qty,price,currency,filament_id,grams_per_unit,active,fulfillment_mode,stock_min_qty,lead_time_days,slug)
                         VALUES('TEST-001','Produto Teste','Integração',3,25,'USD',%s,100,TRUE,'ready_stock',1,2,'produto-teste') RETURNING id""",(filament_id,))
            product_id=cur.fetchone()['id']
            cur.execute("INSERT INTO customers(name,email,phone) VALUES('Cliente Teste','cliente@example.com','5551112222') RETURNING id")
            customer_id=cur.fetchone()['id']
        c.commit()
    finally:c.close()

    client=flask_app.test_client()
    with client.session_transaction() as sess:
        sess['user_id']=user_id;sess['full_name']='Integration Tester'

    # 1. Painéis principais e estoque seguro carregam.
    assert client.get('/catalog/manage').status_code==200
    assert client.get('/orders').status_code==200
    assert client.get('/production/stock').status_code==200
    r=client.get('/?tab=stock',follow_redirects=False)
    assert r.status_code in (302,303) and '/stock-admin' in r.headers.get('Location','')
    assert client.get('/stock-admin').status_code==200

    # 1b. Nova cor/material pode ser cadastrada diretamente no estoque seguro.
    r=client.post('/stock-admin/add',data={
        'material':'PETG','color':'Turquesa Teste','brand':'Marca Teste',
        'remaining_g':'750','spool_weight_g':'1000','purchase_cost':'24.50',
        'currency':'USD','min_g':'80','supplier':'Fornecedor Teste','location':'Prateleira T'
    },follow_redirects=False)
    assert r.status_code in (302,303) and '/stock-admin' in r.headers.get('Location','')
    new_filament_id=scalar("SELECT id FROM filaments WHERE material='PETG' AND color='Turquesa Teste' ORDER BY id DESC LIMIT 1")
    assert new_filament_id
    assert float(scalar('SELECT remaining_g FROM filaments WHERE id=%s',(new_filament_id,)))==750.0
    assert float(scalar('SELECT reserved_g FROM filaments WHERE id=%s',(new_filament_id,)))==0.0
    assert int(scalar("SELECT COUNT(*) FROM inventory_movements WHERE filament_id=%s AND movement_type='initial_stock'",(new_filament_id,)))==1
    assert b'Turquesa Teste' in client.get('/stock-admin').data

    # 2. Peso suspeito no fluxo legado continua bloqueado.
    before_batches=int(scalar('SELECT COUNT(*) FROM production_batches'))
    r=client.post('/production/stock/create',data={'product_id':product_id,'quantity':'1','filament_id':filament_id,'grams_per_unit':'0.77'},follow_redirects=False)
    assert r.status_code in (302,303)
    assert int(scalar('SELECT COUNT(*) FROM production_batches'))==before_batches
    assert float(scalar('SELECT reserved_g FROM filaments WHERE id=%s',(filament_id,)))==0.0

    # 3. Fluxo legado válido permanece compatível.
    r=client.post('/production/stock/create',data={'product_id':product_id,'quantity':'2','filament_id':filament_id,'grams_per_unit':'100'},follow_redirects=False)
    assert r.status_code in (302,303)
    batch_id=scalar("SELECT id FROM production_batches WHERE product_id=%s ORDER BY id DESC LIMIT 1",(product_id,))
    assert batch_id
    assert float(scalar('SELECT reserved_g FROM filaments WHERE id=%s',(filament_id,)))==200.0
    r=client.post(f'/stock-admin/{filament_id}/adjust',data={'grams':'-900'},follow_redirects=False)
    assert r.status_code in (302,303)
    assert float(scalar('SELECT remaining_g FROM filaments WHERE id=%s',(filament_id,)))==1000.0
    r=client.post(f'/production/stock/{batch_id}/complete',data={'actual_grams':'190'},follow_redirects=False)
    assert r.status_code in (302,303)
    assert float(scalar('SELECT reserved_g FROM filaments WHERE id=%s',(filament_id,)))==0.0
    assert float(scalar('SELECT remaining_g FROM filaments WHERE id=%s',(filament_id,)))==810.0
    assert int(scalar('SELECT stock_qty FROM products WHERE id=%s',(product_id,)))==5

    # 4. Multicor: duas cores são reservadas separadamente e cancelar devolve ambas.
    r=client.post('/production/stock/create-multicolor',data={
        'product_id':str(product_id),'quantity':'1',
        'material_filament_id':[str(filament_id),str(black_id)],
        'material_grams_per_unit':['70','30']
    },follow_redirects=False)
    assert r.status_code in (302,303)
    multi_id=scalar("SELECT id FROM production_batches WHERE product_id=%s ORDER BY id DESC LIMIT 1",(product_id,))
    assert float(scalar('SELECT reserved_g FROM filaments WHERE id=%s',(filament_id,)))==70.0
    assert float(scalar('SELECT reserved_g FROM filaments WHERE id=%s',(black_id,)))==30.0
    assert int(scalar('SELECT COUNT(*) FROM production_batch_materials WHERE batch_id=%s',(multi_id,)))==2
    r=client.post(f'/production/stock/{multi_id}/cancel-multicolor',follow_redirects=False)
    assert r.status_code in (302,303)
    assert float(scalar('SELECT reserved_g FROM filaments WHERE id=%s',(filament_id,)))==0.0
    assert float(scalar('SELECT reserved_g FROM filaments WHERE id=%s',(black_id,)))==0.0
    assert float(scalar('SELECT remaining_g FROM filaments WHERE id=%s',(filament_id,)))==810.0
    assert float(scalar('SELECT remaining_g FROM filaments WHERE id=%s',(black_id,)))==500.0

    # 5. Uma cor de detalhe pode ter menos de 1 g, desde que o peso total da peça seja válido.
    r=client.post('/production/stock/create-multicolor',data={
        'product_id':str(product_id),'quantity':'1',
        'material_filament_id':[str(filament_id),str(black_id)],
        'material_grams_per_unit':['99.5','0.5']
    },follow_redirects=False)
    assert r.status_code in (302,303)
    accent_id=scalar("SELECT id FROM production_batches WHERE product_id=%s ORDER BY id DESC LIMIT 1",(product_id,))
    assert float(scalar('SELECT reserved_g FROM filaments WHERE id=%s',(filament_id,)))==99.5
    assert float(scalar('SELECT reserved_g FROM filaments WHERE id=%s',(black_id,)))==0.5
    r=client.post(f'/production/stock/{accent_id}/cancel-multicolor',follow_redirects=False)
    assert r.status_code in (302,303)

    # 6. Multicor concluído consome cada cor pelo valor real e adiciona a peça uma única vez.
    r=client.post('/production/stock/create-multicolor',data={
        'product_id':str(product_id),'quantity':'1',
        'material_filament_id':[str(filament_id),str(black_id)],
        'material_grams_per_unit':['70','30']
    },follow_redirects=False)
    assert r.status_code in (302,303)
    multi_id=scalar("SELECT id FROM production_batches WHERE product_id=%s ORDER BY id DESC LIMIT 1",(product_id,))
    c=conn()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT id,filament_id FROM production_batch_materials WHERE batch_id=%s ORDER BY id',(multi_id,))
            mats=cur.fetchall()
    finally:c.close()
    actual_data={}
    for m in mats:
        actual_data[f"actual_material_{m['id']}"]='65' if m['filament_id']==filament_id else '35'
    r=client.post(f'/production/stock/{multi_id}/complete-multicolor',data=actual_data,follow_redirects=False)
    assert r.status_code in (302,303)
    assert float(scalar('SELECT remaining_g FROM filaments WHERE id=%s',(filament_id,)))==745.0
    assert float(scalar('SELECT remaining_g FROM filaments WHERE id=%s',(black_id,)))==465.0
    assert float(scalar('SELECT reserved_g FROM filaments WHERE id=%s',(filament_id,)))==0.0
    assert float(scalar('SELECT reserved_g FROM filaments WHERE id=%s',(black_id,)))==0.0
    assert int(scalar('SELECT stock_qty FROM products WHERE id=%s',(product_id,)))==6

    # 7. Lote histórico inválido pode ser revertido sem apagar o histórico.
    c=conn()
    try:
        with c.cursor() as cur:
            cur.execute('UPDATE filaments SET remaining_g=remaining_g-0.77 WHERE id=%s',(black_id,))
            cur.execute('UPDATE products SET stock_qty=stock_qty+1 WHERE id=%s',(product_id,))
            cur.execute("""INSERT INTO production_batches(product_id,filament_id,mode,quantity,grams_per_unit,reserved_g,consumed_g,status,invalid_reason,completed_at)
                         VALUES(%s,%s,'stock',1,0.77,0.77,0.77,'completed','Peso de teste inválido',NOW()) RETURNING id""",(product_id,black_id))
            invalid_id=cur.fetchone()['id']
            cur.execute('''INSERT INTO production_batch_materials(batch_id,filament_id,grams_per_unit,reserved_g,consumed_g)
                           VALUES(%s,%s,0.77,0.77,0.77)''',(invalid_id,black_id))
        c.commit()
    finally:c.close()
    before_black=float(scalar('SELECT remaining_g FROM filaments WHERE id=%s',(black_id,)))
    r=client.post(f'/production/stock/{invalid_id}/invalidate',data={'reason':'teste revertido'},follow_redirects=False)
    assert r.status_code in (302,303)
    assert scalar('SELECT status FROM production_batches WHERE id=%s',(invalid_id,))=='invalidated'
    assert float(scalar('SELECT remaining_g FROM filaments WHERE id=%s',(black_id,)))==before_black+0.77
    assert int(scalar('SELECT stock_qty FROM products WHERE id=%s',(product_id,)))==6

    # 8. Pedido público de pronta entrega reserva uma unidade.
    r=client.get(f'/request-quote?product={product_id}&source=integration_test')
    assert r.status_code==200
    r=client.post('/request-quote',data={'mode':'catalog','product_id':str(product_id),'name':'Comprador Teste','email':'buyer@example.com','phone':'5559990000','quantity':'1'},follow_redirects=False)
    assert r.status_code in (302,303) and '/request/' in r.headers.get('Location','')
    request_id=scalar("SELECT id FROM customer_requests WHERE email='buyer@example.com' ORDER BY id DESC LIMIT 1")
    assert request_id
    assert int(scalar('SELECT reserved_stock_qty FROM customer_requests WHERE id=%s',(request_id,)))==1
    assert int(scalar('SELECT reserved_stock_qty FROM products WHERE id=%s',(product_id,)))==1

    # 9. Rejeição libera a reserva pronta.
    r=client.post(f'/online-requests/{request_id}/status',data={'status':'rejected','admin_notes':'teste'},follow_redirects=False)
    assert r.status_code in (302,303)
    assert int(scalar('SELECT reserved_stock_qty FROM products WHERE id=%s',(product_id,)))==0

    # 10. Fila de impressão: reserva -> consumo -> ajuste real.
    c=conn()
    try:
        with c.cursor() as cur:
            cur.execute("""INSERT INTO quotes(quote_number,customer_id,title,project_type,status,currency,subtotal,total,filament_id,estimated_grams)
                         VALUES('LEG-INT-001',%s,'Pedido impressão','customer','execution','USD',50,50,%s,100) RETURNING id""",(customer_id,filament_id))
            quote_id=cur.fetchone()['id']
            cur.execute("INSERT INTO projects(quote_id,customer_id,project_type,name,status) VALUES(%s,%s,'customer','Pedido impressão','execution')",(quote_id,customer_id))
        c.commit()
    finally:c.close()
    r=client.post(f'/printing/{quote_id}/queue',data={'filament_id':filament_id,'estimated_grams':'100'},follow_redirects=False)
    assert r.status_code in (302,303)
    assert float(scalar('SELECT reserved_g FROM filaments WHERE id=%s',(filament_id,)))==100.0
    before=float(scalar('SELECT remaining_g FROM filaments WHERE id=%s',(filament_id,)))
    r=client.post(f'/printing/{quote_id}/start',data={'machine_id':machine_id},follow_redirects=False)
    assert r.status_code in (302,303)
    assert float(scalar('SELECT reserved_g FROM filaments WHERE id=%s',(filament_id,)))==0.0
    assert float(scalar('SELECT remaining_g FROM filaments WHERE id=%s',(filament_id,)))==before-100.0
    r=client.post(f'/printing/{quote_id}/complete',data={'actual_grams':'90'},follow_redirects=False)
    assert r.status_code in (302,303)
    assert scalar('SELECT status FROM quotes WHERE id=%s',(quote_id,))=='completed'
    assert float(scalar('SELECT remaining_g FROM filaments WHERE id=%s',(filament_id,)))==before-90.0
    assert scalar('SELECT status FROM machines WHERE id=%s',(machine_id,))=='available'

    # 11. Migrações são idempotentes.
    run_migrations()
    assert int(scalar('SELECT COUNT(*) FROM schema_migrations'))>=3

    print('Integration smoke tests passed.')


if __name__=='__main__':
    main()
