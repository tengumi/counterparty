"""Input adapters and the counterparty repository boundary.

TODO:
- определить read-only CounterpartySource protocol;
- сделать JSON основным adapter и распаковать $date/$numberLong;
- добавить CSV unflatten adapter как fallback;
- нормализовать schema aliases, включая cofounders[].isActive/active;
- собрать индексы по ИНН, ОГРН, нормализованному названию и ОКВЭД;
- возвращать success/empty/partial/unavailable/denied/invalid;
- не логировать raw snapshots и PII.
"""
