import openai
import os
import json
from dotenv import load_dotenv
from pymongo import MongoClient
import pymongo
import re 

load_dotenv(override=True)

# OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY")

# MongoDB connection
mongodb_uri = os.getenv("MONGO_URI")
client = pymongo.MongoClient(mongodb_uri)
db = client["chop-n-shop"]
recipes_collection = db["recipes"]

def generate_recipe(prompt):
    """
    Generate a recipe using OpenAI based on the user's prompt.
    """
    try:
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a professional recipe generator."},
                {"role": "user", "content": f"Create a detailed recipe based on the following request: {prompt}. "
                                             f"Return the recipe in JSON format with the following keys: "
                                             f"name, ingredients (list), simplified ingredients (list), instructions (list), prep_time, cook_time, total_time."}
            ],
            max_tokens=500,
            temperature=0.7
        )
        recipe_json = response.choices[0].message.content.strip()
        recipe_data = json.loads(recipe_json)  # Convert JSON string to Python dictionary
        return recipe_data
    except json.JSONDecodeError:
        print("Error: Could not decode JSON from OpenAI response.")
        return None
    except Exception as e:
        print(f"Error generating recipe: {e}")
        return None

def save_recipe_to_db(recipe_data):
    """
    Save the recipe to the MongoDB `recipes` collection, including simplified ingredients.
    """
    try:
        recipe_document = {
            "name": recipe_data.get('name', 'Unnamed Recipe'),
            "ingredients": recipe_data.get('ingredients', []),  # Original ingredients
            "simplified_ingredients": recipe_data.get('simplified_ingredients', []),  # Simplified ingredients
            "instructions": recipe_data.get('instructions', []),
            "prep_time": recipe_data.get('prep_time', 'Unknown'),
            "cook_time": recipe_data.get('cook_time', 'Unknown'),
            "total_time": recipe_data.get('total_time', 'Unknown'),
        }
        result = recipes_collection.insert_one(recipe_document)
        print(f"Recipe saved successfully with ID: {result.inserted_id}")
        return result.inserted_id
    except Exception as e:
        print(f"Error saving recipe to database: {e}")
        return None

def generate_and_save_recipe(user_prompt):
    """
    Generate a recipe using OpenAI and save it to MongoDB.
    """
    print("Generating recipe...")
    recipe_data = generate_recipe(user_prompt)
    
    if not recipe_data:
        print("Failed to generate recipe.")
        return None

    print("Saving recipe to database...")
    recipe_id = save_recipe_to_db(recipe_data)
    return recipe_id

# Example Usage
if __name__ == "__main__":
    # User's natural language input
    user_prompt = "I want a recipe for a quick and easy vegetarian lasagna."
    
    # Generate and save recipe
    recipe_id = generate_and_save_recipe(user_prompt)
    
    if recipe_id:
        print(f"Recipe successfully saved to database with ID: {recipe_id}")
    else:
        print("Recipe generation and saving failed.")