import time


def main():
    print("lead worker stub started")
    while True:
        time.sleep(30)
        print("lead worker stub alive")


if __name__ == "__main__":
    main()
