# utils/ai.py
import os
import json
import google.generativeai as genai
import datetime
import pathlib

def log_gemini_interaction(prompt: str, response: str) -> None:
    """Log a Gemini interaction to a file."""
    # Create data directory if it doesn't exist
    data_dir = pathlib.Path(__file__).parent.parent / 'data'
    data_dir.mkdir(exist_ok=True)
    
    # Create a filename with timestamp
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = data_dir / f'gemini_interaction_{timestamp}.json'
    
    # Create the log entry
    log_entry = {
        'timestamp': datetime.datetime.now().isoformat(),
        'prompt': prompt,
        'response': response
    }
    
    # Write to file
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(log_entry, f, indent=2, ensure_ascii=False)

def generate_gemini_message(user_instruction: str, existing_services: list) -> list:
    """
    Generate a response using the Gemini API.
    :param user_instruction: The user's natural-language instruction.
    :param existing_services: A list of dicts with keys [day, time, activities].
    :return: A list of new/modified service dicts from the AI.
    """

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("Warning: GEMINI_API_KEY not set in environment.")
    genai.configure(api_key=api_key)

    model = genai.GenerativeModel(model_name="gemini-2.0-flash")

    # Convert existing services to JSON so we can embed them in the system prompt
    existing_json = json.dumps(existing_services, indent=2)

    print("BUILDING SYSTEM PROMPT")
    # Build a system prompt that shows the AI the current database state
    system_prompt = f"""
You are a church service scheduler assistant. Below is the CURRENT list of all worship services that exist:

CURRENT SERVICES (JSON):
{existing_json}

User instruction: "{user_instruction}"

RULES FOR YOUR RESPONSE:
- You must return ONLY a JSON array describing the *changes* to make:
  - To delete a service, include an object with "day", "time", and "delete":true.
  - To add a new service, provide "day", "time", and "activities".
  - To update an existing service's time or day, you should delete the old one and add the new one with the same activities (unless the user explicitly wants to change them).
  - If user doesn't mention changing activities, preserve the old ones from the existing list.
- DO NOT repeat the entire list of services; only the ones that are changed/added/deleted.
- For any new or updated service, if user doesn't say to change the activities, keep them as they are from the existing service.
- Output must be valid JSON. No extra commentary, just a list of objects.
- Time must be in 12-hour format with AM/PM (e.g., "10:30 AM", "2:00 PM")
- Day must be a full day name (e.g., "Sunday", "Monday")

Example possible response:
[
  {{
    "day": "Sunday",
    "time": "10:30 AM",
    "delete": true
  }},
  {{
    "day": "Sunday",
    "time": "10:45 AM",
    "activities": ["Singing", "Prayer", "Preaching"]
  }}
]


Now produce only the JSON array that implements the user's desired changes:
    """.strip()

    # Get the response from Gemini

    print("GENERATING CONTENT")
    response = model.generate_content(
        system_prompt,
        generation_config={'response_mime_type': 'application/json'}
    )

    # write the response exactly as it is to a file
    print("WRITING RESPONSE")
    with open('gemini_response.txt', 'w') as f:
        f.write(response.text)

    # Log the interaction before processing
    log_gemini_interaction(user_instruction, response.text)

    # Clean up the response text to ensure it's valid JSON
    cleaned_text = response.text.strip()
    if cleaned_text.startswith('```json'):
        cleaned_text = cleaned_text[7:]
    if cleaned_text.endswith('```'):
        cleaned_text = cleaned_text[:-3]
    cleaned_text = cleaned_text.strip()

    # Attempt to parse the model's raw text as JSON
    try:
        services = json.loads(cleaned_text)
        if not isinstance(services, list):
            # If the model just returned one object, wrap in a list
            services = [services]
            
        # Validate each service object
        for service in services:
            if not isinstance(service, dict):
                raise ValueError("Invalid service object: " + str(service))
            if 'day' not in service or 'time' not in service:
                raise ValueError("Service missing required fields: " + str(service))
                
            # Ensure day is properly formatted
            if not isinstance(service['day'], str):
                raise ValueError("Day must be a string: " + str(service))
            service['day'] = service['day'].strip().title()
            
            # Ensure time is properly formatted
            if not isinstance(service['time'], str):
                raise ValueError("Time must be a string: " + str(service))
            try:
                # Validate time format
                datetime.datetime.strptime(service['time'].strip(), '%I:%M %p')
            except ValueError:
                raise ValueError("Invalid time format in service: " + str(service))
            
            # Ensure activities is a list if present
            if 'activities' in service and not isinstance(service['activities'], list):
                if isinstance(service['activities'], str):
                    service['activities'] = [act.strip() for act in service['activities'].split(',')]
                else:
                    raise ValueError("Activities must be a list: " + str(service))
                    
        return services
    except json.JSONDecodeError as e:
        print("Gemini raw text that caused JSON Error: ",  repr(cleaned_text))
        raise ValueError("Invalid JSON response from Gemini: " + cleaned_text)
    except Exception as e:
        raise ValueError("Error processing Gemini response: " + str(e))
