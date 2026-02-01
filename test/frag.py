import asyncio
import os
from frag import FragmentAPI

async def main():
    print("--- Fragment +888 Number Checker ---")
    print("You need to provide your Fragment session details.")
    print("Open https://fragment.com/my/numbers in your browser, open Developer Tools (F12),")
    print("go to Network tab, filter by 'XHR', refresh page, and look for a request to 'api'.")
    print("Look at the Request Headers (Cookie) and the Payload/Params (hash).")
    print("----------------------------------------------------------------")

    # Hardcoded credentials provided by user
    hash_val = "690c4526a3a439c200"
    stel_ssid = "22be7a24128374f0c6_15879312291724142247"
    stel_ton_token = "8Jg_aD8xZYaS59-9P0s8_vhx6j23rXqMRGumEFQgKwPKE0ogeIDf5qPLNcrIrT16ie9ohiva-Fj3fuv2zYafuEHvpUYfr-RmeSWBMJMWDbpsncNF-UFqhk6KnPm_2aGHBEv_L6fvXqpM0DJhjue7yUANeSHYzdHTolTLVkSBBWmhN344dch3arx0WAdXE-FdK3CK9ZeZ"
    stel_token = "" # Not found in provided list, leaving empty

    '''
    # Get credentials
    hash_val = input("Enter 'hash' value: ").strip()
    stel_ssid = input("Enter 'stel_ssid' cookie value: ").strip()
    stel_ton_token = input("Enter 'stel_ton_token' cookie value: ").strip()
    stel_token = input("Enter 'stel_token' cookie value: ").strip()
    '''

    if not all([hash_val, stel_ssid, stel_ton_token]):
        print("Error: Missing hardcoded credentials.")
        return

    api = FragmentAPI(
        hash=hash_val,
        stel_ssid=stel_ssid,
        stel_ton_token=stel_ton_token,
        stel_token=stel_token
    )

    while True:
        number = input("\nEnter +888 number to check (or 'q' to quit): ").strip().replace("+", "").replace(" ", "")
        
        if number.lower() == 'q':
            break

        if not number.startswith("888"):
            print("Warning: Number should usually start with 888.")
        
        print(f"Checking {number}...")
        
        try:
            # According to the user provided logic:
            # check_is_number_free returns True if "confirm_button" != "Proceed anyway".
            is_free = await api.check_is_number_free(number)
            
            if is_free:
                print(f"Result: {number} seems to be FREE/AVAILABLE (or at least safe to sell/claim).")
            else:
                print(f"Result: {number} is BUSY/CONNECTED (Status: Proceed anyway detected).")
                
        except Exception as e:
            print(f"Error checking number: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
