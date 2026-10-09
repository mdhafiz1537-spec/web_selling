import os

while True:
    command = input(">>> ").lower()

    if command == "open chrome":
        os.system("start chrome")

    elif command == "open calculator":
        os.system("start calc")

    elif command == "open notepad":
        os.system("start notepad")

    elif command == "open youtube":
        os.system("start https://youtube.com")

    elif command == "open vscode":
        os.system("start code")

    elif command == "open music":
        os.system("start Media player")

    elif command == "exit":
        print("Goodbye!")
        break

    else:
        print("I don't understand that command.")