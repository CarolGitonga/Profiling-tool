import instaloader

# Create instaloader instance
L = instaloader.Instaloader()

# Ask user for login credentials
username = input("Enter your Instagram username: ")
password = input("Enter your Instagram password: ")

# Try login
try:
    L.login(username, password)
    print("✅ Login successful!")

    # Save session to file
    L.save_session_to_file(filename=f"{username}_session")
    print(f"🔐 Session saved as {username}_session")

except Exception as e:
    print(f"❌ Login failed: {e}")
