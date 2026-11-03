-- Sample SQL dump
CREATE TABLE users (
    id INT PRIMARY KEY,
    name VARCHAR(100),
    email VARCHAR(200),
    phone VARCHAR(20)
);

INSERT INTO users VALUES (1, 'Alice Johnson', 'alice@gmail.com', '555-1234');
INSERT INTO users VALUES (2, 'Bob Smith', 'bob@yahoo.com', '555-5678');
INSERT INTO users VALUES (3, 'Carol White', 'carol@gmail.com', '555-9012');
