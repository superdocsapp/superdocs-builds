import os
import httpx

def check_superdocs(api_key: str) -> bool:
    """Verifies the SuperDocs API Key using a test endpoint handshake."""
    url = "https://api.superdocs.app/v1/agents/whoami"  # standard whoami endpoint mentioned in the task docs
    headers = {"Authorization": f"Bearer {api_key}"}
    
    print(f"Connecting to SuperDocs at {url}...")
    try:
        with httpx.Client() as client:
            response = client.get(url, headers=headers)
            if response.status_code == 200:
                print("✓ SuperDocs API Key: VALID")
                print(f"  Account Info: {response.json()}")
                return True
            else:
                print(f"✗ SuperDocs API Key: INVALID (HTTP {response.status_code})")
                print(f"  Response: {response.text}")
                return False
    except Exception as e:
        print(f"✗ SuperDocs connection failed: {e}")
        return False

def check_openai(api_key: str) -> bool:
    """Verifies the OpenAI API Key by making a minimal completion request."""
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 5
    }
    
    print(f"Connecting to OpenAI at {url}...")
    try:
        with httpx.Client() as client:
            response = client.post(url, headers=headers, json=payload, timeout=10.0)
            if response.status_code == 200:
                print("✓ OpenAI API Key: VALID")
                return True
            else:
                print(f"✗ OpenAI API Key: INVALID (HTTP {response.status_code})")
                print(f"  Response: {response.json().get('error', {}).get('message', response.text)}")
                return False
    except Exception as e:
        print(f"✗ OpenAI connection failed: {e}")
        return False

if __name__ == "__main__":
    # Check environment variables
    superdocs_key = os.getenv("SUPERDOCS_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    
    # Try to load from .env file if it exists
    if not superdocs_key or not openai_key:
        env_path = ".env"
        if os.path.exists(env_path):
            print("Reading keys from local .env file...")
            with open(env_path, "r") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        if k.strip() == "SUPERDOCS_API_KEY":
                            superdocs_key = v.strip().strip('"').strip("'")
                        elif k.strip() == "OPENAI_API_KEY":
                            openai_key = v.strip().strip('"').strip("'")

    if not superdocs_key:
        print("✗ SUPERDOCS_API_KEY is not set in environment or .env file.")
    else:
        check_superdocs(superdocs_key)
        
    print("-" * 50)
    
    if not openai_key:
        print("✗ OPENAI_API_KEY is not set in environment or .env file.")
    else:
        check_openai(openai_key)
