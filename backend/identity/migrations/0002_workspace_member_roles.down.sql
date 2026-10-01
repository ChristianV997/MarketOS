-- Reverses 0002 up. Dropping the column discards assigned roles (memberships stay).
ALTER TABLE workspace_members DROP COLUMN role;
