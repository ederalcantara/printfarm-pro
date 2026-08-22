from marketing import run_due_instagram_posts


if __name__ == '__main__':
    processed = run_due_instagram_posts(limit=10)
    print(f'INSTAGRAM_SCHEDULER processed={processed}', flush=True)
