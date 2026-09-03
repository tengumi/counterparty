"""LangGraph workflow and session state.

TODO:
- собрать parse -> resolve -> route -> load -> analyze -> compose -> validate;
- поддержать lookup, compare, similar и follow_up;
- распараллелить анализ нескольких компаний и затем выполнить reduce;
- хранить компактный SessionState через SQLite checkpointer;
- изолировать состояние по user_id/thread_id и не переносить его в новую сессию;
- разрешать неоднозначность через уточнение, а не скрытый выбор модели.
"""
