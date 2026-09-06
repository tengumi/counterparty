/** Компании проверки и действия с ними. Цвет плашек не обозначает риск. */

import { ProjectStatusMark } from '../../components/StatusMark';
import { PlusSIcon } from '@alfalab/icons-glyph/PlusSIcon';
import { HouseMIcon } from '@alfalab/icons-glyph/HouseMIcon';
import { BarChartMIcon } from '@alfalab/icons-glyph/BarChartMIcon';
import type { CompanyRef, ProjectStatus } from '../../mocks/types';
import { COMPANY_LIMIT } from '../../mocks/types';
import styles from './S2.module.css';

interface Props {
  readonly companies: readonly CompanyRef[];
  readonly status: ProjectStatus;
  readonly isDemo: boolean;
  readonly onOpenCompany: (companyId: string) => void;
  readonly onAddCompany: () => void;
  readonly onCompare: () => void;
}

export function CompanyContextStrip(props: Props) {
  const [first, ...rest] = props.companies;
  const limitReached = props.companies.length >= COMPANY_LIMIT;

  return (
    <div aria-label="Компании проверки" className={styles.companies} role="group">
      {first ? (
        <button
          className={styles.companyName}
          onClick={() => props.onOpenCompany(first.id)}
          title={first.name}
          type="button"
        >
          <HouseMIcon aria-hidden="true" className={styles.companyIcon} />
          <span className={styles.companyLabel}>{first.name}</span>
        </button>
      ) : (
        <span className={styles.emptyCompanies}>Компании не добавлены</span>
      )}
      {props.isDemo ? <span className={styles.demoTag}>Учебный пример</span> : null}
      {rest.length > 0 ? (
        <button aria-label={`Все компании проверки: ${props.companies.length}`} className={styles.moreCompanies}
          onClick={props.onAddCompany} type="button">ещё {rest.length}</button>
      ) : null}
      <button
        className={styles.companyAction}
        disabled={limitReached}
        onClick={props.onAddCompany}
        type="button"
      >
        <PlusSIcon aria-hidden="true" />
        Добавить
      </button>
      {limitReached ? (
        <span className={styles.limitNote}>
          В проверке можно хранить до {COMPANY_LIMIT} компаний. Уберите лишние ИНН
        </span>
      ) : null}
      {props.companies.length >= 2 ? (
        <button className={`${styles.companyAction} ${styles.compareAction}`} onClick={props.onCompare} type="button">
          <BarChartMIcon aria-hidden="true" />
          Сравнить
        </button>
      ) : null}
      {props.status !== 'in_progress' ? (
        <span className={styles.projectStatus}>
          <ProjectStatusMark status={props.status} />
        </span>
      ) : null}
    </div>
  );
}
