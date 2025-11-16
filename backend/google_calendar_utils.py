from google_auth_oauthlib.flow import InstalledAppFlow

def generate_new_google_token():
    flow = InstalledAppFlow.from_client_secrets_file(
        'credentials.json',  # your client secret file
        scopes=['https://www.googleapis.com/auth/calendar']
    )
    creds = flow.run_local_server(port=0)
    
    # Save the new token for future API calls
    with open('token.json', 'w') as token_file:
        token_file.write(creds.to_json())

    print("✅ New Google token generated and saved to token.json")
