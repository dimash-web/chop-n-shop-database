from fastapi import FastAPI, HTTPException, Depends, status,Header
from pydantic import BaseModel, condecimal
from bson import ObjectId
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext
from typing import List, Optional
from decimal import Decimal
from datetime import datetime, timedelta
from enum import Enum
from main import users_collection, stores_collection, items_collection, recipes_collection, grocery_lists_collection
from openai_grocerylist import generate_grocery_list 
from openai_json_recipe import generate_recipe, save_recipe_to_db
from openai_recipe_grocery_list import generate_grocery_list_from_recipe
import jwt
from jwt.exceptions import PyJWTError

app = FastAPI()

SECRET_KEY = "2@1&]."  # Use a strong secret key in production
ALGORITHM = "HS256"  # Algorithm for encoding and decoding JWT tokens
ACCESS_TOKEN_EXPIRE_MINUTES = 300  # Expiry time for the token


# CORS middleware for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for testing, adjust as needed
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Cryptography (for hashing passwords)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_access_token(data: dict, expires_delta: timedelta = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_current_user(authorization: str = Header(...)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing or invalid")
    try:
        token = authorization.split(" ")[1]  # "Bearer <token>"
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User ID not found in token")
        return user_id
    except PyJWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {str(e)}")

# Enum for dietary preferences
class DietaryPreference(str, Enum):
    vegan = "vegan"
    vegetarian = "vegetarian"
    gluten_free = "gluten-free"
    lactose_free = "lactose-free"
    pescetarian = "pescetarian"
    none = "none"

# Pydantic models for input validation
class UserPreferences(BaseModel):
    Budget: float
    Grocery_items: List[str]
    Dietary_preferences: str
    Allergies: List[str]
    Store_preference: Optional[str] = None

class User(BaseModel):
    first_name: str
    email: str
    password: str
    allergies: Optional[str] = None

class LoginUser(BaseModel):
    email: str
    password: str

class Item(BaseModel):
    Item_name: str
    Store_name: str
    Price: float
    Ingredients: list[str]
    Calories: int

class RecipeGroceryItem(BaseModel):
    ingredient: str
    item_name: str
    price: float
    store: str

class RecipeGroceryListResponse(BaseModel):
    grocery_list: List[RecipeGroceryItem]
    total_cost: float
    over_budget: float

class RecipePrompt(BaseModel):
    recipe_prompt: str

class GroceryItem(BaseModel):
    ingredient: str
    item_name: str
    price: float
    store: str

# Define user preferences model
class RecipeListUserPreferences(BaseModel):
    Budget: float
    Dietary_preferences: str
    Allergies: List[str]

# Define request and response models
class RecipeRequest(BaseModel):
    recipe_name: str
    user_preferences: RecipeListUserPreferences

class RecipeResponse(BaseModel):
    recipe_id: str
    recipe_name: str
    grocery_list: List[GroceryItem]
    total_cost: float
    over_budget: float


@app.post("/generate_recipe_with_grocery_list", response_model=RecipeResponse)
async def generate_recipe_with_grocery_list(recipe_request: RecipeRequest):
    """
    Search for a recipe by name and generate a grocery list based on its ingredients.
    """
    try:
        # Step 1: Check if the recipe exists
        recipe = recipes_collection.find_one({"name": recipe_request.recipe_name})
        if not recipe:
            raise HTTPException(status_code=404, detail="This recipe does not exist.")

        # Step 2: Generate the grocery list using the existing recipe's ID
        recipe_id = recipe["_id"]
        grocery_list, total_cost, over_budget = generate_grocery_list_from_recipe(
            recipe_id=recipe_id, user_preferences=recipe_request.user_preferences.dict()
        )

        # Step 3: Return the response
        return RecipeResponse(
            recipe_id=str(recipe_id),
            recipe_name=recipe["name"],
            grocery_list=[GroceryItem(**item) for item in grocery_list],
            total_cost=total_cost,
            over_budget=over_budget,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")

    
# Utility functions for password handling
def hash_password(password: str):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

# Routes for user registration and authentication

# User Registration Route
@app.post("/register/")
async def add_user(user: User):
    existing_user = users_collection.find_one({"email": user.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already in use")

    hashed_password = hash_password(user.password)

    user_document = {
        "first_name": user.first_name,
        "email": user.email,
        "password": hashed_password,
        "allergies": user.allergies.split(",") if user.allergies else []
    }

    try:
        result = users_collection.insert_one(user_document)
        return {"message": f"User {user.first_name} added with ID: {result.inserted_id}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while adding the user: {str(e)}")

# User Login Route
@app.post("/login/")
async def login(user: LoginUser):
    existing_user = users_collection.find_one({"email": user.email})
    if not existing_user or not verify_password(user.password, existing_user["password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Generate JWT token
    access_token = create_access_token(data={"sub": str(existing_user["_id"])})
    return {"message": "Login successful", "access_token": access_token, "token_type": "bearer"}

# Route to generate a grocery list based on user preferences
@app.post("/generate_grocery_list/")
async def generate_grocery_list_endpoint(user_preferences: UserPreferences, current_user: str = Depends(get_current_user)):
    try:
        # Validate input items
        if not user_preferences.Grocery_items:
            raise HTTPException(status_code=400, detail="Items list cannot be empty.")

        # Handle the store name being None
        store_preference = user_preferences.Store_preference if user_preferences.Store_preference else None

        # Generate grocery list based on preferences
        grocery_list = generate_grocery_list({
            "Budget": user_preferences.Budget,
            "Grocery_items": user_preferences.Grocery_items,
            "Dietary_preferences": user_preferences.Dietary_preferences,
            "Allergies": user_preferences.Allergies,
            "Store_preference": store_preference,  # Safely pass None if no store preference
        })

        # Remove _id if present before inserting into the database
        if "_id" in grocery_list:
            del grocery_list["_id"]

        # Insert the generated grocery list into the collection with user association
        grocery_list["user_id"] = current_user  # Associate the list with the logged-in user
        grocery_lists_collection.insert_one(grocery_list)

        # Return the grocery list with its new _id
        grocery_list["_id"] = str(grocery_list["_id"])
        return {"grocery_list": grocery_list}
    except Exception as e:
        print(f"Error generating grocery list: {e}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred. Please try again.")

# Route to fetch previous grocery lists for a user
@app.get("/grocery_lists")
async def get_grocery_lists(current_user: str = Depends(get_current_user)):
    try:
        grocery_lists = grocery_lists_collection.find({"user_id": current_user})
        if not grocery_lists:
            return {"grocery_lists": []}
            
        grocery_list_items = []
        for list_item in grocery_lists:
            list_item["_id"] = str(list_item["_id"])
            grocery_list_items.append(list_item)
            
        return {"grocery_lists": grocery_list_items}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

@app.delete("/grocery_lists/{list_id}")
async def delete_grocery_list(list_id: str, current_user: str = Depends(get_current_user)):
    try:
        if not list_id or list_id == "undefined":
            raise HTTPException(status_code=400, detail="Invalid list ID")
            
        result = grocery_lists_collection.delete_one({
            "_id": ObjectId(list_id), 
            "user_id": current_user
        })
        
        if result.deleted_count == 0:
            raise HTTPException(
                status_code=404, 
                detail="Grocery list not found or you don't have permission to delete it"
            )
            
        return {"message": "Grocery list deleted successfully"}
        
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid list ID format")
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"An error occurred while deleting the grocery list: {str(e)}"
        )

# Route to store a grocery list for a user
# @app.post("/users/{user_id}/grocery-lists/")
# async def create_grocery_list(user_id: str, grocery_list: GroceryList):
#     user = users_collection.find_one({"_id": ObjectId(user_id)})
#     if not user:
#         raise HTTPException(status_code=404, detail="User not found")

#     grocery_list_document = grocery_list.dict()
#     grocery_list_document["created_at"] = datetime.utcnow()

#     update_result = users_collection.update_one(
#         {"_id": ObjectId(user_id)},
#         {"$push": {"grocery_lists": grocery_list_document}}
#     )

#     if update_result.modified_count == 1:
#         return {"message": "Grocery list created successfully"}
#     else:
#         raise HTTPException(status_code=500, detail="Error saving grocery list")

# Route to fetch all available items (can be useful for frontend)
@app.get("/items/")
async def get_items():
    items = list(items_collection.find())
    return [{"Item_name": item["Item_name"], "Price": item["Price"]} for item in items]

# Route to fetch all stores (can be useful for frontend)
@app.get("/stores/")
async def get_stores():
    stores = list(stores_collection.find())
    return [{"Store_name": store["Store_name"]} for store in stores]

@app.post("/generate_recipe/")
async def generate_recipe_route(prompt: RecipePrompt):
    try:
        # Call the function directly
        recipe = generate_recipe(prompt.recipe_prompt)
        if not recipe:
            raise HTTPException(status_code=400, detail="Failed to generate recipe. Please try again.")
        
        recipe_id = save_recipe_to_db(recipe)
        if not recipe_id:
            raise HTTPException(status_code=500, detail="Failed to save recipe to database.")
        return {"recipe": recipe}

    except Exception as e:
        print(f"Error generating recipe: {e}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@app.get("/recipes/{recipe_name}/")
async def get_recipe_by_name(recipe_name: str):
    """
    Fetch a recipe by its name.
    """
    try:
        recipe = recipes_collection.find_one({"name": recipe_name})
        if not recipe:
            raise HTTPException(status_code=404, detail="Recipe not found")

        # Convert ObjectId to string and return the recipe
        recipe["_id"] = str(recipe["_id"])
        return recipe

    except Exception as e:
        print(f"Error fetching recipe by name: {e}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")
