import requests
import os
import sys

def upload_document(file_path, account_id="default_account"):
    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        return

    url = "http://localhost:8001/knowledgebase/"
    
    print(f"Uploading {file_path} for account {account_id}...")
    
    try:
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, "text/markdown")}
            data = {"account_id": account_id}
            
            response = requests.post(url, files=files, data=data)
            
            if response.status_code == 200:
                print("Success!")
                print(response.json())
            else:
                print(f"Failed with status {response.status_code}")
                print(response.text)
                
    except requests.exceptions.ConnectionError:
        print(f"Error: Could not connect to API at {url}. Is the server running?")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    # Default to dummy file if no arg provided
    target_file = "scripts/data/dummy_guide.md"
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_path = os.path.join(project_root, target_file)
    
    if len(sys.argv) > 1:
        target_path = sys.argv[1]
        
    upload_document(target_path)
