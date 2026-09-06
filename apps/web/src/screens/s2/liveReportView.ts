import type {
  Availability,
  FactValue,
  JsonValue,
  ReportRecord,
  SectionName,
} from '../../api/reportContracts';

export const sectionTitles: Readonly<Record<SectionName, string>> = {
  profile: 'Реквизиты',
  status: 'Статус',
  activities: 'Деятельность',
  financials: 'Финансы',
  coefficients: 'Коэффициенты',
  founders: 'Учредители и руководство',
  tax_systems: 'Налогообложение',
  contacts: 'Контакты',
  execution_proceedings: 'Взыскания',
  arbitration: 'Суды',
  procurements: 'Государственные закупки',
  licenses: 'Лицензии',
  inspections: 'Проверки ведомств',
  related_companies: 'Связанные компании',
  branches: 'Филиалы',
  risk_signals: 'Сигналы источника',
  zsk: 'ЗСК',
};
export const availabilityText: Readonly<Record<Availability, string>> = {
  available: 'Данные предоставлены',
  missing: 'В отчёте нет этих сведений',
  present_empty: 'Источник содержит пустое значение',
  invalid: 'Сведения не удалось прочитать',
  restricted: 'Эти сведения недоступны',
};
export const fieldLabels: Readonly<Record<string, string>> = {
  proceeds: 'Выручка',
  profit: 'Прибыль',
  total_assets: 'Активы',
  totalAssets: 'Активы',
  equity: 'Капитал',
  capitals: 'Капитал',
  cash: 'Денежные средства',
  bankroll: 'Денежные средства',
  receivables: 'Дебиторская задолженность',
  accounts_payable: 'Кредиторская задолженность',
  accountsPayable: 'Кредиторская задолженность',
  current_assets: 'Оборотные активы',
  stocks: 'Запасы',
  noncurrent_assets: 'Внеоборотные активы',
  fixed_assets: 'Основные средства',
  fixedAssets: 'Основные средства',
  balance_total_liabilities_side: 'Баланс пассивов',
  totalLiabilities: 'Баланс пассивов',
  long_term_total: 'Долгосрочные обязательства',
  long_term_other: 'Прочие долгосрочные обязательства',
  short_term_total: 'Краткосрочные обязательства',
  short_term_borrowed: 'Заёмные средства',
  borrowedFunds: 'Заёмные средства',
  assets: 'Активы',
  liabilities: 'Пассивы',
  proceedings: 'Взыскания',
  arbitration: 'Суды',
  bank_risk: 'Оценка банка',
  currentAssets: 'Оборотные активы',
  uncurrentAssets: 'Внеоборотные активы',
  longTermDuties: 'Долгосрочные обязательства',
  shortTermLiabilities: 'Краткосрочные обязательства',
  total: 'Всего',
  common: 'Основные сведения',
  year: 'Год',
  amount: 'Сумма',
  active: 'Действующее',
  number: 'Номер',
  date: 'Дата',
  shortName: 'Краткое название',
  fullName: 'Полное название',
  inn: 'ИНН',
  ogrn: 'ОГРН',
  kpp: 'КПП',
  okpo: 'ОКПО',
  address: 'Адрес',
  registrationDate: 'Дата регистрации',
  yearsFromRegistration: 'Лет с регистрации',
  email: 'Электронная почта',
  website: 'Сайт',
  companySize: 'Размер компании',
  riskLevel: 'Риск по оценке банка',
  zskRiskLevel: 'ЗСК',
  status: 'Статус',
  reasonName: 'Причина статуса',
  code: 'Код',
  description: 'Описание',
  name: 'Название',
  issuingAuthority: 'Выдавший орган',
  issueDate: 'Дата выдачи',
  authorityName: 'Орган',
  inspectionStatus: 'Статус проверки',
  erpId: 'Номер проверки',
  form: 'Форма проверки',
  startDate: 'Дата начала',
  endDate: 'Дата окончания',
  shareCapital: 'Уставный капитал',
  share: 'Доля',
  dateFrom: 'Дата начала',
  positionName: 'Должность',
  positionDate: 'Дата назначения',
  full_name: 'Полное название',
  short_name: 'Краткое название',
  count: 'Количество',
  tenderWinnerCnt: 'Победы',
  contractSignedCnt: 'Подписанные контракты',
  contractSignedAmt: 'Сумма контрактов',
  procurementsYear: 'Год закупок',
  federalLawCode: 'Закон',
  sustainability: 'Финансовая устойчивость',
  solvency: 'Платёжеспособность',
  profitability: 'Рентабельность',
  branchesCount: 'Количество филиалов',
  phone: 'Телефон',
  phoneNumber: 'Телефон',
  commonCount: 'Количество дел по источнику',
  commonAmount: 'Сумма дел по источнику',
  pfCount: 'Истец · завершённые · количество',
  pfAmount: 'Истец · завершённые · сумма',
  paCount: 'Истец · обжалование · количество',
  paAmount: 'Истец · обжалование · сумма',
  ppCount: 'Истец · рассматриваются · количество',
  ppAmount: 'Истец · рассматриваются · сумма',
  dfCount: 'Ответчик · завершённые · количество',
  dfAmount: 'Ответчик · завершённые · сумма',
  daCount: 'Ответчик · обжалование · количество',
  daAmount: 'Ответчик · обжалование · сумма',
  dpCount: 'Ответчик · рассматриваются · количество',
  dpAmount: 'Ответчик · рассматриваются · сумма',
  plaintiffCount: 'Истец · количество',
  plaintiffAmount: 'Истец · сумма',
  defendantCount: 'Ответчик · количество',
  defendantAmount: 'Ответчик · сумма',
};
const sourceSections: Readonly<Record<string, SectionName>> = {
  baseInfo: 'profile',
  status: 'status',
  kindsOfActivityInfo: 'activities',
  finReports: 'financials',
  coefficient: 'coefficients',
  foundersInfo: 'founders',
  taxSystem: 'tax_systems',
  phones: 'contacts',
  executionProceedings: 'execution_proceedings',
  arbitrationCases: 'arbitration',
  arbitrationByStatus: 'arbitration',
  procurements: 'procurements',
  licenses: 'licenses',
  inspections: 'inspections',
  relatedCompanies: 'related_companies',
  branchesInfo: 'branches',
  reputationalRisks: 'risk_signals',
  zskRiskLevel: 'zsk',
};

/** Groups thousands with a space; touches no digit and performs no calculation. */
export function groupDigits(value: string): string {
  const [whole = '', fraction] = value.split('.');
  const sign = whole.startsWith('-') ? '-' : '';
  const grouped = whole.replace(/^-/, '').replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  const decimals = fraction && /[1-9]/.test(fraction) ? `,${fraction}` : '';
  return `${sign}${grouped}${decimals}`;
}

/** String grouping keeps every decimal digit intact and performs no calculation. */
export function formatDecimal(value: string, currency?: string | null): string {
  if (!/^-?\d+(\.\d+)?$/.test(value)) return 'Число в неизвестном формате';
  return `${groupDigits(value)}${currency ? ` ${currency === 'RUB' ? '₽' : currency}` : ''}`;
}
export function sourceDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return 'Дата не указана';
  return `${new Intl.DateTimeFormat('ru-RU', { timeZone: 'UTC', day: '2-digit', month: '2-digit', year: 'numeric' }).format(date)} (UTC)`;
}

const _DATE = /^\d{4}-\d\d-\d\d(?:[T ]|$)/;

/** A stored date/timestamp shown to a person: "2 марта 2023", never an ISO string. */
export function prettyDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat('ru-RU', {
    timeZone: 'UTC',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(date);
}
export function factText(fact: FactValue): string {
  if (fact.availability !== 'available') return availabilityText[fact.availability];
  if (!fact.evidence_refs.length) return 'Значение не показываем: основание недоступно';
  if (fact.value === null) return 'Сведения не удалось прочитать';
  if (fact.value_type === 'decimal')
    return typeof fact.value === 'string'
      ? formatDecimal(fact.value, fact.currency)
      : 'Число в неизвестном формате';
  if (typeof fact.value === 'boolean') return fact.value ? 'Да' : 'Нет';
  if (fact.value === 'available') return 'Данные предоставлены';
  if (typeof fact.value === 'string' && (fact.value_type === 'date' || _DATE.test(fact.value)))
    return prettyDate(fact.value);
  return String(fact.value);
}
export function factLabel(fact: FactValue): string {
  const leaf = fact.key.split(/[./]/).at(-1) ?? fact.key;
  return fieldLabels[leaf] ?? (fact.label.startsWith('/') ? 'Сведение источника' : fact.label);
}
export interface DisplayRow {
  readonly key: string;
  readonly label: string;
  readonly value: string;
  readonly refs: readonly string[];
  readonly period?: number | string | null;
  readonly fact?: FactValue;
}
export function factRow(fact: FactValue): DisplayRow {
  return {
    key: fact.key,
    label: factLabel(fact),
    value: factText(fact),
    refs: fact.evidence_refs,
    period: fact.period,
    fact,
  };
}
export function recordRows(record: ReportRecord): {
  title: string;
  rows: readonly DisplayRow[];
  note?: string | null;
} {
  const fields = (items: readonly (readonly [string, string | null | undefined])[]): DisplayRow[] =>
    items
      .filter((item) => item[1] != null)
      .map(([label, value]) => ({
        key: label,
        label,
        value: value as string,
        refs: record.evidence_refs,
      }));
  switch (record.kind) {
    case 'financial_period':
      return {
        title: `${record.year} год`,
        rows: [
          record.proceeds,
          record.profit,
          record.total_assets,
          record.equity,
          record.cash,
          record.receivables,
          record.accounts_payable,
          ...record.additional_facts,
        ].map(factRow),
      };
    case 'profile_record':
      return {
        title: 'Из предоставленного отчёта',
        rows: fields([
          ['Полное название', record.full_name],
          ['Краткое название', record.short_name],
          ['ИНН', record.inn],
          ['КПП', record.kpp],
          ['ОКПО', record.okpo],
          ['Адрес', record.address],
          ['Дата регистрации', record.registration_date],
          ['Электронная почта', record.email],
          ['Сайт', record.website],
          ['Размер компании', record.company_size],
        ]),
      };
    case 'activity':
      return {
        title: record.is_primary ? 'Основная деятельность' : 'Дополнительная деятельность',
        rows: fields([
          ['ОКВЭД', record.code],
          ['Описание', record.description],
        ]),
      };
    case 'proceeding':
      return {
        title: record.number ?? 'Исполнительное производство',
        rows: [
          ...fields([['Дата', record.started_at]]),
          factRow(record.active),
          factRow(record.amount),
        ],
      };
    case 'arbitration_aggregate':
      return {
        title: `${record.role === 'plaintiff' ? 'Истец' : 'Ответчик'} · ${record.aggregation === 'year' ? `${record.year} год` : record.case_status_raw}`,
        rows: [factRow(record.count), factRow(record.amount)],
        note: 'Агрегат источника, не отдельное дело. Годовые и статусные итоги не складываются.',
      };
    case 'procurement_aggregate':
      return {
        title: `${record.year} · ${record.law_code}`,
        rows: [
          factRow(record.winners_count),
          factRow(record.contracts_count),
          factRow(record.contracts_amount),
        ],
        note: 'Участие и подписание контракта не подтверждают его исполнение.',
      };
    case 'license':
      return {
        title: record.number ?? 'Лицензия',
        rows: fields([
          ['Название', record.name],
          ['Выдавший орган', record.authority],
          ['Дата выдачи', record.issue_date],
          ['Статус источника', record.status_raw],
        ]),
      };
    case 'inspection':
      return {
        title: record.external_id ?? 'Проверка ведомства',
        rows: fields([
          ['Форма', record.form],
          ['Орган', record.authority],
          ['Начало', record.start_date],
          ['Окончание', record.end_date],
          ['Статус источника', record.status_raw],
        ]),
      };
    case 'related_entity':
      return {
        title: record.name ?? 'Связанная компания',
        rows: fields([
          ['ИНН', record.inn],
          ['ОГРН', record.ogrn],
        ]),
        note: 'Характер связи определяется по источнику; наличие полного отчёта проверяется отдельно.',
      };
    case 'risk_signal':
      return {
        title: record.polarity === 'positive' ? 'В пользу компании' : 'Настораживает',
        rows: fields([['Сигнал', record.source_name]]),
        note: record.interpretation_note,
      };
  }
}
export function evidenceTitle(path: string): string {
  const tokens = path.split('/').slice(1);
  const section = sourceSections[tokens[0] ?? ''];
  if (tokens.at(-1) === 'total') return fieldLabels[tokens.at(-2) ?? ''] ?? 'Сумма источника';
  if (path.endsWith('/longTermDuties/others')) return 'Прочие долгосрочные обязательства';
  return (
    fieldLabels[tokens.at(-1) ?? ''] ??
    (section ? sectionTitles[section] : 'Сведение предоставленного отчёта')
  );
}
export function evidenceSection(path: string): string {
  const section = sourceSections[path.split('/')[1] ?? ''];
  return section ? sectionTitles[section] : 'Сведения отчёта';
}
export interface FragmentRow {
  readonly label: string;
  readonly value: string;
}
export function fragmentRows(value: JsonValue, label: string): readonly FragmentRow[] {
  if (value === null) return [{ label, value: 'Пустое значение в источнике' }];
  if (Array.isArray(value))
    return value.length
      ? value.flatMap((item, index) => fragmentRows(item, `${label} · запись ${index + 1}`))
      : [{ label, value: 'Пустой список в источнике' }];
  if (typeof value === 'object') {
    const entries = Object.entries(value);
    if (!entries.length) return [{ label, value: 'Пустой объект в источнике' }];
    const first = entries[0];
    if (entries.length === 1 && first && first[0].startsWith('$'))
      return fragmentRows(first[1], label);
    return entries.flatMap(([key, item]) =>
      fragmentRows(item, `${label} · ${fieldLabels[key] ?? 'Дополнительное сведение'}`),
    );
  }
  const text =
    typeof value === 'boolean'
      ? value
        ? 'Да'
        : 'Нет'
      : typeof value === 'number' && !Number.isSafeInteger(value)
        ? 'Точность числа в исходном фрагменте не подтверждена'
        : typeof value === 'number' && Math.abs(value) >= 10000
          ? groupDigits(String(value))
          : String(value);
  return [{ label, value: text }];
}
