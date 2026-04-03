-- Drink Menu & Recipe Book — MariaDB 10.6.24 Schema

CREATE TABLE IF NOT EXISTS ingredients (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(255) NOT NULL UNIQUE,
    in_cabinet  BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS drinks (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    image_url       VARCHAR(2048),
    abv             INT NOT NULL,          -- stored as 0-1000 (divide by 10 for display)
    recipe_type     ENUM('inline','link') NOT NULL
);

CREATE TABLE IF NOT EXISTS drink_ingredients (
    drink_id        INT NOT NULL,
    ingredient_id   INT NOT NULL,
    PRIMARY KEY (drink_id, ingredient_id),
    FOREIGN KEY (drink_id) REFERENCES drinks(id) ON DELETE CASCADE,
    FOREIGN KEY (ingredient_id) REFERENCES ingredients(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS recipes (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    drink_id        INT NOT NULL UNIQUE,
    instructions    TEXT,                  -- populated for inline type
    url             VARCHAR(2048),         -- populated for link type
    FOREIGN KEY (drink_id) REFERENCES drinks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS admins (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    username        VARCHAR(255) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL  -- bcrypt hash
);

CREATE TABLE IF NOT EXISTS sessions (
    token       VARCHAR(255) PRIMARY KEY,
    admin_id    INT NOT NULL,
    created_at  DATETIME NOT NULL,
    expires_at  DATETIME NOT NULL,
    FOREIGN KEY (admin_id) REFERENCES admins(id) ON DELETE CASCADE
);
