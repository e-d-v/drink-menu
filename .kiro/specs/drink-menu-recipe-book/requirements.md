# Requirements Document

## Introduction

An online drink menu and recipe book web application. The system allows any visitor to browse drinks that can currently be made with the ingredients available in the cabinet, with filtering and sorting capabilities. Each drink links to either inline recipe instructions or an external URL. An admin interface (login-protected) allows management of ingredients and recipes.

The frontend is built with Angular v21 compiled to static HTML/CSS/JS, served via cPanel. The backend is a Python 3.11.14 application running as a Python Application on cPanel, backed by a MariaDB 10.6.24 database. The UI is mobile-first, optimized for iPad use.

## Glossary

- **System**: The drink menu and recipe book web application as a whole
- **Frontend**: The Angular v21 static web application
- **API**: The Python 3.11.14 backend REST API
- **Database**: The MariaDB 10.6.24 relational database
- **Drink**: A named beverage with associated metadata (name, image URL, alcohol percentage, ingredients, recipe)
- **Recipe**: The instructions or external link associated with a Drink
- **Inline_Recipe**: A recipe stored as text instructions within the system
- **Link_Recipe**: A recipe stored as an external URL that redirects the user
- **Ingredient**: A named item that may be present in the cabinet
- **Cabinet**: The current collection of Ingredients available for making drinks
- **Admin**: An authenticated user with permission to manage Drinks and the Cabinet
- **Visitor**: An unauthenticated user browsing the drink menu

---

## Requirements

### Requirement 1: Browse Available Drinks

**User Story:** As a Visitor, I want to see all drinks I can currently make, so that I know what is available with the ingredients on hand.

#### Acceptance Criteria

1. WHEN the Visitor loads the drink menu page, THE Frontend SHALL request the list of Drinks from the API filtered to only those whose required Ingredients are all present in the Cabinet.
2. THE API SHALL return only Drinks for which every associated Ingredient exists in the Cabinet.
3. WHEN the drink list is returned, THE Frontend SHALL display each Drink with its name, image preview, and alcohol percentage.
4. IF a Drink has no image URL, THEN THE Frontend SHALL display a placeholder image in place of the drink image.

---

### Requirement 2: Sort and Filter Drinks

**User Story:** As a Visitor, I want to sort and filter the drink list, so that I can find drinks that match my preferences.

#### Acceptance Criteria

1. THE Frontend SHALL provide a control to sort the displayed Drink list by alcohol percentage in ascending or descending order.
2. THE Frontend SHALL provide a control to filter the displayed Drink list by one or more Ingredients, showing only Drinks that contain all selected Ingredients.
3. WHEN a sort or filter control is changed, THE Frontend SHALL update the displayed Drink list without a full page reload.
4. WHEN no Drinks match the active filter, THE Frontend SHALL display a message indicating no drinks are available for the selected criteria.

---

### Requirement 3: View Drink Recipe

**User Story:** As a Visitor, I want to view the recipe for a drink, so that I know how to make it.

#### Acceptance Criteria

1. WHEN a Visitor selects a Drink with an Inline_Recipe, THE Frontend SHALL navigate to a recipe detail page displaying the drink name, image, alcohol percentage, ingredient list, and text instructions.
2. THE Frontend SHALL render newline characters in Inline_Recipe instructions as visual line breaks.
3. WHEN a Visitor selects a Drink with a Link_Recipe, THE Frontend SHALL redirect the Visitor's browser to the URL stored for that recipe.
4. THE API SHALL store and return the recipe type (inline or link) for each Drink so the Frontend can determine the correct behavior.

---

### Requirement 4: Admin Authentication

**User Story:** As an Admin, I want to log in to a protected admin area, so that only authorized users can manage drinks and ingredients.

#### Acceptance Criteria

1. THE System SHALL provide a login page accessible at a dedicated admin login route.
2. WHEN an Admin submits valid credentials, THE API SHALL return a session token and THE Frontend SHALL store it for subsequent authenticated requests.
3. WHEN an Admin submits invalid credentials, THE API SHALL return an error response and THE Frontend SHALL display an error message.
4. WHILE an Admin is not authenticated, THE Frontend SHALL redirect any request to admin routes to the login page.
5. WHEN an Admin logs out, THE Frontend SHALL discard the session token and redirect to the login page.
6. THE API SHALL reject any request to admin endpoints that does not include a valid session token with a 401 response.

---

### Requirement 5: Manage Cabinet Ingredients

**User Story:** As an Admin, I want to manage the ingredients currently in my cabinet, so that the drink list reflects what I can actually make.

#### Acceptance Criteria

1. WHEN an authenticated Admin loads the ingredient management page, THE Frontend SHALL display the current list of all Ingredients and their cabinet status.
2. WHEN an authenticated Admin toggles an Ingredient's cabinet status, THE API SHALL update the Cabinet to reflect the change.
3. WHEN an authenticated Admin submits a new Ingredient name, THE API SHALL add the Ingredient to the system and THE Frontend SHALL display it in the ingredient list.
4. IF an Admin submits a new Ingredient with a name that already exists, THEN THE API SHALL return an error and THE Frontend SHALL display a message indicating the Ingredient already exists.

---

### Requirement 6: Add New Recipe — Inline Type

**User Story:** As an Admin, I want to add a new drink with inline instructions, so that Visitors can read the recipe directly on the site.

#### Acceptance Criteria

1. WHEN an authenticated Admin selects the option to add a new recipe with inline instructions, THE Frontend SHALL present a form with fields for drink name, image URL, alcohol percentage, ingredients selection, and text instructions.
2. WHEN the Admin submits the inline recipe form with all required fields populated, THE API SHALL store the new Drink and its Inline_Recipe in the Database.
3. IF the Admin submits the inline recipe form with any required field missing, THEN THE Frontend SHALL display a validation error and SHALL NOT submit the form to the API.
4. THE Frontend SHALL allow the Admin to enter multi-line text instructions using the Enter key to insert newlines.
5. THE Frontend SHALL provide the list of ingredients for the Admin to select from.

---

### Requirement 7: Add New Recipe — Link Type

**User Story:** As an Admin, I want to add a new drink that links to an external recipe, so that I can reference existing recipes without duplicating content.

#### Acceptance Criteria

1. WHEN an authenticated Admin selects the option to add a new recipe via URL import, THE Frontend SHALL present a form with fields for drink name, image URL, alcohol percentage, ingredients selection, and recipe URL.
2. WHEN the Admin submits the link recipe form with all required fields populated, THE API SHALL store the new Drink and its Link_Recipe URL in the Database.
3. IF the Admin submits the link recipe form with any required field missing, THEN THE Frontend SHALL display a validation error and SHALL NOT submit the form to the API.
4. IF the Admin submits the link recipe form with a malformed URL, THEN THE Frontend SHALL display a validation error and SHALL NOT submit the form to the API.
5. THE Frontend SHALL provide the list of ingredients for the Admin to select from.

---

### Requirement 8: Edit and Delete Recipes

**User Story:** As an Admin, I want to edit or delete existing recipes, so that I can keep the drink menu accurate and up to date.

#### Acceptance Criteria

1. WHEN an authenticated Admin loads the recipe management page, THE Frontend SHALL display a list of all Drinks in the system regardless of Cabinet status.
2. WHEN an authenticated Admin selects a Drink to edit, THE Frontend SHALL present a pre-populated form with the Drink's current data.
3. WHEN an authenticated Admin submits an edited Drink form with all required fields populated, THE API SHALL update the Drink record in the Database.
4. WHEN an authenticated Admin confirms deletion of a Drink, THE API SHALL remove the Drink and its associated Recipe from the Database.
5. IF the API returns an error during edit or delete, THEN THE Frontend SHALL display an error message to the Admin.

---

### Requirement 9: Image Handling

**User Story:** As an Admin, I want to associate an image URL with each drink, so that Visitors see a visual preview without the system needing to store image files.

#### Acceptance Criteria

1. THE System SHALL store drink images as URLs only and SHALL NOT provide file upload functionality.
2. WHEN an Admin provides an image URL for a Drink, THE API SHALL store the URL string in the Database.
3. WHEN THE Frontend renders a Drink image, THE Frontend SHALL use the stored URL as the image source.

---

### Requirement 10: API Data Integrity

**User Story:** As a developer, I want the API to enforce data integrity, so that the Database remains consistent.

#### Acceptance Criteria

1. THE API SHALL require drink name, alcohol percentage, recipe type, and at least one Ingredient for every Drink record.
2. IF a request to create or update a Drink omits a required field, THEN THE API SHALL return a 400 response with a descriptive error message.
3. THE API SHALL store alcohol percentage as a numeric value between 0 and 1000 inclusive, and the Frontend SHALL display this value divided by 10.
4. IF a request provides an alcohol percentage outside the range 0 to 1000, THEN THE API SHALL return a 400 response.
