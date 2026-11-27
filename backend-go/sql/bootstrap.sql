INSERT INTO public.alembic_version (version_num) VALUES ('0028_coach_chat_reviews');
INSERT INTO public.app_state (id, data_revision, calendar_head_version) VALUES (1, 0, 0);
SELECT pg_catalog.setval('public.app_state_id_seq', 1, false);
