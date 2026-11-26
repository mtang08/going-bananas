-- Synthetic workflow schema. The Python dashboard currently stores private review files.
CREATE TABLE coach_chat_reviews (
    mode text NOT NULL,
    id uuid NOT NULL,
    state jsonb NOT NULL,
    current boolean NOT NULL,
    PRIMARY KEY (mode, id)
);
CREATE UNIQUE INDEX coach_chat_current ON coach_chat_reviews (mode) WHERE current;
CREATE TABLE coach_chat_receipts (
    mode text NOT NULL,
    client_message_id uuid NOT NULL,
    digest text NOT NULL,
    PRIMARY KEY (mode, client_message_id)
);

CREATE TABLE coach_chat_file_imports (mode text PRIMARY KEY);
