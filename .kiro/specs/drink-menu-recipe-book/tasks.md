# Implementation Plan: Drink Menu & Recipe Book

## Overview

Implement the drink menu and recipe book web application incrementally: database schema first, then the Python REST API, then the Angular frontend. Each phase builds on the previous, ending with full integration.

## Tasks

- [ ] 1. Set up database schema and backend project structure
  - Create the MariaDB schema with all tables: `ingredients`, `drinks`, `drink_ingredients`, `recipes`, `admins`, `sessions`
  - Set up Python 3.11.14 project with `requirements.txt` (Flask or FastAPI, PyMySQL/mysql-connector, bcrypt, hypothesis, pytest)
  - Create database connection module with connection pooling
  - Seed one admin user with a bcrypt-hashed password for initial access
  - _Requirements: 10.1, 10.3_

- [ ] 2. Implement public drink endpoints
  - [ ] 2.1 Implement `GET /drinks` — return only drinks whose every ingredient has `in_cabinet = true`
    - Query joins `drinks`, `drink_ingredients`, `ingredients` and filters by cabinet availability
    - Return JSON array of drink list items (id, name, image_url, abv, recipe_type)
    - _Requirements: 1.1, 1.2_

  - [ ]* 2.2 Write property test for cabinet filtering correctness
    - **Property 1: Cabinet filtering correctness**
    - **Validates: Requirements 1.2**

  - [ ] 2.3 Implement `GET /drinks/:id` — return single drink with recipe detail
    - Include ingredients list, instructions, and url fields
    - Return 404 if drink not found
    - _Requirements: 3.4_

  - [ ]* 2.4 Write property test for recipe type round-trip
    - **Property 6: Recipe type round-trip**
    - **Validates: Requirements 3.4**

  - [ ] 2.5 Implement `GET /ingredients` — return all ingredients with `in_cabinet = true`
    - _Requirements: 2.2_

- [ ] 3. Implement authentication endpoints
  - [ ] 3.1 Implement `POST /auth/login` — validate credentials, create session token, return token
    - Use bcrypt to verify password hash
    - Store session in `sessions` table with expiry
    - Return 401 on invalid credentials
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ] 3.2 Implement `POST /auth/logout` — invalidate session token
    - Delete session row from `sessions` table
    - _Requirements: 4.5_

  - [ ] 3.3 Implement auth middleware for all `/admin/*` routes
    - Validate `Authorization: Bearer <token>` header against `sessions` table
    - Return 401 if missing, invalid, or expired
    - _Requirements: 4.6_

  - [ ]* 3.4 Write property test for API auth rejection
    - **Property 8: API rejects unauthenticated admin requests**
    - **Validates: Requirements 4.6**

- [ ] 4. Implement admin ingredient endpoints
  - [ ] 4.1 Implement `GET /admin/ingredients` — return all ingredients with cabinet status
    - _Requirements: 5.1_

  - [ ] 4.2 Implement `POST /admin/ingredients` — add new ingredient
    - Validate unique name; return 409 on duplicate
    - _Requirements: 5.3, 5.4_

  - [ ] 4.3 Implement `PATCH /admin/ingredients/:id` — toggle `in_cabinet` status
    - _Requirements: 5.2_

  - [ ]* 4.4 Write property test for cabinet toggle round-trip
    - **Property 10: Cabinet toggle round-trip**
    - **Validates: Requirements 5.2**

  - [ ]* 4.5 Write property test for add ingredient round-trip
    - **Property 11: Add ingredient round-trip**
    - **Validates: Requirements 5.3**

- [ ] 5. Implement admin drink/recipe endpoints
  - [ ] 5.1 Implement `GET /admin/drinks` — return all drinks regardless of cabinet state
    - _Requirements: 8.1_

  - [ ]* 5.2 Write property test for admin recipe list completeness
    - **Property 15: Admin recipe list shows all drinks**
    - **Validates: Requirements 8.1**

  - [ ] 5.3 Implement `POST /admin/drinks` — create drink with inline or link recipe
    - Validate required fields: name, abv (0–1000), recipe_type, at least one ingredient
    - Return 400 with descriptive error on missing/invalid fields
    - _Requirements: 6.2, 7.2, 10.1, 10.2, 10.4_

  - [ ]* 5.4 Write property test for inline drink creation round-trip
    - **Property 12: Inline drink creation round-trip**
    - **Validates: Requirements 6.2**

  - [ ]* 5.5 Write property test for link drink creation round-trip
    - **Property 14: Link drink creation round-trip**
    - **Validates: Requirements 7.2**

  - [ ]* 5.6 Write property test for API required field enforcement
    - **Property 20: API required field enforcement**
    - **Validates: Requirements 10.1, 10.2**

  - [ ]* 5.7 Write property test for ABV storage and range validation
    - **Property 21: ABV storage and display transformation**
    - **Validates: Requirements 10.3, 10.4**

  - [ ] 5.8 Implement `PUT /admin/drinks/:id` — update drink and recipe
    - Same validation as POST; return 404 if drink not found
    - _Requirements: 8.3_

  - [ ]* 5.9 Write property test for edit drink round-trip
    - **Property 17: Edit drink round-trip**
    - **Validates: Requirements 8.3**

  - [ ] 5.10 Implement `DELETE /admin/drinks/:id` — delete drink and associated recipe
    - Return 404 if drink not found; cascade deletes handled by FK constraints
    - _Requirements: 8.4_

  - [ ]* 5.11 Write property test for delete drink removes record
    - **Property 18: Delete drink removes record**
    - **Validates: Requirements 8.4**

  - [ ]* 5.12 Write property test for image URL round-trip
    - **Property 19: Image URL round-trip**
    - **Validates: Requirements 9.2**

- [ ] 6. Backend checkpoint — Ensure all tests pass
  - Ensure all pytest unit tests and Hypothesis property tests pass, ask the user if questions arise.

- [ ] 7. Set up Angular v21 project structure
  - Scaffold Angular v21 app with routing module
  - Configure `HttpClientModule` and environment files for API base URL
  - Set up Jest for unit tests and fast-check for property-based tests
  - Create shared `ErrorNotificationComponent` for surfacing API errors
  - _Requirements: 4.4_

- [ ] 8. Implement Angular services and auth guard
  - [ ] 8.1 Implement `AuthService` — `POST /auth/login`, `POST /auth/logout`, token storage in `localStorage`
    - Store/retrieve token as `Authorization: Bearer <token>` header
    - _Requirements: 4.2, 4.5_

  - [ ] 8.2 Implement `AuthGuard` — redirect to `/admin/login` if no valid token in storage
    - _Requirements: 4.4_

  - [ ]* 8.3 Write property test for auth guard covers all admin routes
    - **Property 7: Auth guard covers all admin routes**
    - **Validates: Requirements 4.4**

  - [ ] 8.4 Implement `DrinkService` — `GET /drinks`, `GET /drinks/:id`
    - _Requirements: 1.1, 3.1_

  - [ ] 8.5 Implement `IngredientService` — `GET /ingredients`
    - _Requirements: 2.2_

  - [ ] 8.6 Implement `IngredientAdminService` — `GET /admin/ingredients`, `POST /admin/ingredients`, `PATCH /admin/ingredients/:id`
    - Attach auth header on all calls; handle 401 by triggering logout
    - _Requirements: 5.1, 5.2, 5.3_

  - [ ] 8.7 Implement `RecipeAdminService` — `GET /admin/drinks`, `POST /admin/drinks`, `PUT /admin/drinks/:id`, `DELETE /admin/drinks/:id`
    - Attach auth header; handle 401 by triggering logout
    - _Requirements: 8.1, 8.3, 8.4_

- [ ] 9. Implement public-facing Angular components
  - [ ] 9.1 Implement `DrinkCardComponent` — display drink name, image (or placeholder), and ABV (abv / 10)
    - _Requirements: 1.3, 1.4, 10.3_

  - [ ]* 9.2 Write property test for drink card renders required fields
    - **Property 2: Drink card renders required fields**
    - **Validates: Requirements 1.3, 1.4**

  - [ ] 9.3 Implement `DrinkMenuComponent` — load drinks on init, render grid of `DrinkCardComponent`
    - Client-side sort by ABV ascending/descending
    - Client-side filter by selected ingredients (only cabinet ingredients shown as filter options)
    - Show "no drinks available" message when filtered list is empty
    - Navigate to `/drink/:id` for inline recipes; redirect browser for link recipes
    - _Requirements: 1.1, 2.1, 2.2, 2.3, 2.4_

  - [ ]* 9.4 Write property test for ingredient filter correctness
    - **Property 3: Ingredient filter correctness**
    - **Validates: Requirements 2.2**

  - [ ] 9.5 Implement `RecipeDetailComponent` — display drink name, image, ABV, ingredient list, and instructions
    - Render `\n` in instructions as visual line breaks (use `white-space: pre-line` or `<br>` substitution)
    - Navigate back to menu on 404
    - _Requirements: 3.1, 3.2_

  - [ ]* 9.6 Write property test for inline recipe detail renders all fields
    - **Property 4: Inline recipe detail renders all fields**
    - **Validates: Requirements 3.1**

  - [ ]* 9.7 Write property test for newline rendering in instructions
    - **Property 5: Newline rendering in instructions**
    - **Validates: Requirements 3.2**

- [ ] 10. Implement admin Angular components
  - [ ] 10.1 Implement `LoginComponent` — admin login form, store token on success, show error on 401
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ] 10.2 Implement `IngredientManagerComponent` — list all ingredients with cabinet toggle and add-ingredient form
    - Show inline error if duplicate ingredient name returned (409)
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [ ]* 10.3 Write property test for ingredient list renders with cabinet status
    - **Property 9: Ingredient list renders with cabinet status**
    - **Validates: Requirements 5.1**

  - [ ] 10.4 Implement `RecipeFormComponent` — shared form for add/edit (inline and link types)
    - Fields: name, image URL, ABV, ingredient multi-select, recipe type toggle, instructions/URL
    - Client-side validation: all required fields, URL format for link type, multi-line text input for inline type
    - Do not submit if form is invalid; show inline validation errors
    - Pre-populate all fields when editing an existing drink
    - _Requirements: 6.1, 6.3, 6.4, 6.5, 7.1, 7.3, 7.4, 7.5, 8.2_

  - [ ]* 10.5 Write property test for required field validation on recipe forms
    - **Property 13: Required field validation on recipe forms**
    - **Validates: Requirements 6.3, 7.3**

  - [ ]* 10.6 Write property test for edit form pre-population
    - **Property 16: Edit form pre-population**
    - **Validates: Requirements 8.2**

  - [ ] 10.7 Implement `RecipeManagerComponent` — list all drinks, link to edit form, confirm-then-delete
    - Show error notification on API error during edit or delete
    - _Requirements: 8.1, 8.4, 8.5_

- [ ] 11. Wire Angular routes and apply mobile-first styles
  - Register all routes: `/`, `/drink/:id`, `/admin/login`, `/admin/ingredients`, `/admin/recipes`, `/admin/recipes/new`, `/admin/recipes/:id/edit`
  - Apply `AuthGuard` to all `/admin/*` routes except `/admin/login`
  - Apply mobile-first CSS (iPad-optimized layout, touch-friendly controls)
  - _Requirements: 4.4_

- [ ] 12. Final checkpoint — Ensure all tests pass
  - Ensure all Jest unit tests, fast-check property tests, pytest unit tests, and Hypothesis property tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at the end of each major phase
- Property tests validate universal correctness; unit tests cover specific examples and error conditions
- ABV is always stored as an integer (0–1000) in the DB and divided by 10 for display
