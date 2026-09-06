/**
 * D1 «Итог проверки»: the AI conclusion and the decision the user records.
 *
 * The two are separate entities (Specs 04 §8, 10 §4). The conclusion is shown
 * with the context version it was drawn from and is marked when the project has
 * moved past it; the decision is written only by the server, so nothing here
 * says «записано» before a 201 came back. A recorded decision is never deleted
 * or rewritten by a newer conclusion — a new decision supersedes the old one
 * and both stay visible.
 */

import { useState } from 'react';
import { Button } from '@alfalab/core-components/button';
import { Radio } from '@alfalab/core-components/radio';
import { Textarea } from '@alfalab/core-components/textarea';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { WorkspaceApiError } from '../../api/client';
import { requestErrorMessage } from '../../api/messages';
import type { ApiProject } from '../../api/contracts';
import {
  createDecision,
  decisionKeys,
  listDecisions,
  listLatestArtifacts,
} from '../../api/decisions';
import type { ApiAnalysisArtifact, ApiUserDecision, CreateDecisionRequest, DecisionOutcome } from '../../api/decisions';
import { workspaceKeys } from '../../api/workspace';
import {
  artifactStaleMark,
  byNewest,
  conditionsLabel,
  decisionDate,
  decisionProblem,
  decisionStaleMark,
  outcomeLabels,
  parseConditions,
} from './decisionView';
import styles from './S2.module.css';

interface Props {
  readonly project: ApiProject;
  /** Opens a numbered basis of the conclusion in the same panel. */
  readonly onOpenEvidence: (evidenceRef: string) => void;
}

const OUTCOMES: readonly DecisionOutcome[] = [
  'ready',
  'ready_with_conditions',
  'not_ready',
  'need_more_info',
];

function isMissing(error: unknown): boolean {
  return error instanceof WorkspaceApiError && (error.status === 404 || error.status === 501);
}

function StaleNote({ mark }: { mark: { label: string; detail: string } | null }) {
  if (mark === null) return null;
  return (
    <p className={styles.proposal} data-testid="stale-mark">
      <span className={styles.decisionStale}>{mark.label}</span> {mark.detail}
    </p>
  );
}

function Conclusion({
  artifact,
  contextVersion,
  onOpenEvidence,
}: {
  artifact: ApiAnalysisArtifact;
  contextVersion: number;
  onOpenEvidence: (evidenceRef: string) => void;
}) {
  return (
    <div className={styles.analysisMemo}>
      <p className={styles.proposal}>Предложение помощника · версия {artifact.version}</p>
      <p className={styles.detailTitle}>{artifact.question}</p>
      <p className={styles.detailValue}>{artifact.summary}</p>
      <StaleNote mark={artifactStaleMark(artifact, contextVersion)} />

      {artifact.grounds.length > 0 ? (
        <>
          <p className={styles.sectionHeading}>Основания</p>
          <ul className={styles.decisionList}>
            {artifact.grounds.map((ground, index) => (
              <li key={index}>
                <span>{ground.text}</span>
                {ground.refs.map((ref) => (
                  <Button key={ref} onClick={() => onOpenEvidence(ref)} size={32} view="text">
                    Основание
                  </Button>
                ))}
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {artifact.unknowns.length > 0 ? (
        <>
          <p className={styles.sectionHeading}>Неизвестное</p>
          <ul className={styles.decisionList}>
            {artifact.unknowns.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </>
      ) : null}

      {artifact.next_actions.length > 0 ? (
        <>
          <p className={styles.sectionHeading}>Следующие шаги</p>
          <ul className={styles.decisionList}>
            {artifact.next_actions.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}

function RecordedDecision({
  decision,
  contextVersion,
  current,
}: {
  decision: ApiUserDecision;
  contextVersion: number;
  current: boolean;
}) {
  return (
    <div className={styles.decisionItem}>
      <p className={styles.recorded}>
        {current ? 'Записано вами' : 'Прежнее решение'} · {decisionDate(decision.created_at)}
      </p>
      <p className={styles.detailValue}>{outcomeLabels[decision.outcome]}</p>
      <p>{decision.rationale}</p>
      {decision.conditions.length > 0 ? (
        <ul className={styles.decisionList}>
          {decision.conditions.map((condition, index) => (
            <li key={index}>{condition}</li>
          ))}
        </ul>
      ) : null}
      {current ? <StaleNote mark={decisionStaleMark(decision, contextVersion)} /> : null}
    </div>
  );
}

export function DecisionPanel({ project, onOpenEvidence }: Props) {
  const queryClient = useQueryClient();
  const artifacts = useQuery({
    queryKey: decisionKeys.artifacts(project.id),
    queryFn: () => listLatestArtifacts(project.id),
    retry: false,
  });
  const decisions = useQuery({
    queryKey: decisionKeys.decisions(project.id),
    queryFn: () => listDecisions(project.id),
    retry: false,
  });

  const [outcome, setOutcome] = useState<DecisionOutcome | null>(null);
  const [rationale, setRationale] = useState('');
  const [conditionsText, setConditionsText] = useState('');
  const [showProblem, setShowProblem] = useState(false);

  const artifact = [...(artifacts.data ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const recorded = byNewest(decisions.data ?? []);
  const latest = recorded[0];

  const record = useMutation({
    mutationFn: (body: CreateDecisionRequest) => createDecision(project.id, body),
    onSuccess: (saved) => {
      queryClient.setQueryData<readonly ApiUserDecision[]>(decisionKeys.decisions(project.id), (previous) =>
        [saved, ...(previous ?? []).filter((item) => item.id !== saved.id)],
      );
      setOutcome(null);
      setRationale('');
      setConditionsText('');
      setShowProblem(false);
      void queryClient.invalidateQueries({ queryKey: decisionKeys.decisions(project.id) });
      // The project's workflow status and latest decision come from the server.
      void queryClient.invalidateQueries({ queryKey: workspaceKeys.project(project.id) });
      void queryClient.invalidateQueries({ queryKey: workspaceKeys.all, exact: true });
    },
  });

  const conditions = parseConditions(conditionsText);
  const problem = decisionProblem(outcome, rationale, conditions);
  // The service does not accept decisions yet; an enabled button would lie.
  const cannotRecord = isMissing(decisions.error);

  return (
    <div className={styles.decision}>
      <section aria-labelledby="decision-conclusion">
        <h3 className={styles.sectionHeading} id="decision-conclusion">
          Вывод помощника
        </h3>
        {artifacts.isPending ? <p className={styles.muted} role="status">Загружаем вывод…</p> : null}
        {artifacts.isError ? (
          <p className={styles.muted}>
            {isMissing(artifacts.error)
              ? 'Вывод помощника пока не сохраняется сервисом проверки. Это не значит, что замечаний нет.'
              : requestErrorMessage(artifacts.error)}
          </p>
        ) : null}
        {artifacts.isSuccess && artifact === undefined ? (
          <p className={styles.muted}>
            Помощник ещё не сформулировал вывод по этой проверке. Решение можно записать и без него.
          </p>
        ) : null}
        {artifact === undefined ? null : (
          <Conclusion
            artifact={artifact}
            contextVersion={project.context_version}
            onOpenEvidence={onOpenEvidence}
          />
        )}
      </section>

      <section aria-labelledby="decision-recorded">
        <h3 className={styles.sectionHeading} id="decision-recorded">
          Ваше решение
        </h3>
        {decisions.isPending ? <p className={styles.muted} role="status">Загружаем решения…</p> : null}
        {decisions.isError ? (
          <p className={styles.muted} data-testid="decisions-unavailable">
            {isMissing(decisions.error)
              ? 'Сервис проверки пока не принимает решения. Записать решение здесь нельзя; вывод и основания остаются доступными.'
              : requestErrorMessage(decisions.error)}
          </p>
        ) : null}
        {recorded.length === 0 && decisions.isSuccess ? (
          <p className={styles.muted}>Решение ещё не записано.</p>
        ) : null}
        {recorded.map((decision, index) => (
          <RecordedDecision
            contextVersion={project.context_version}
            current={index === 0}
            decision={decision}
            key={decision.id}
          />
        ))}
      </section>

      <section aria-labelledby="decision-form">
        <h3 className={styles.sectionHeading} id="decision-form">
          {latest === undefined ? 'Записать решение' : 'Пересмотреть решение'}
        </h3>
        <fieldset className={styles.decisionOutcomes}>
          <legend className={styles.visuallyHidden}>Решение по проверке</legend>
          {OUTCOMES.map((value) => (
            <span className={styles.decisionOutcome} key={value}>
              <Radio
                checked={outcome === value}
                disabled={cannotRecord}
                label={outcomeLabels[value]}
                name="decision-outcome"
                onChange={() => setOutcome(value)}
                size={24}
              />
            </span>
          ))}
        </fieldset>
        <Textarea
          aria-label="Основание решения"
          autosize={true}
          block={true}
          disabled={cannotRecord}
          label="Почему вы так решили"
          minRows={2}
          onChange={(_event, payload) => setRationale(payload.value)}
          placeholder="Например: аванс снижаем до 30%, пока нет подтверждения наличия"
          value={rationale}
        />
        <Textarea
          aria-label="Условия решения"
          autosize={true}
          block={true}
          disabled={cannotRecord}
          label={outcome === null ? 'Условия или недостающие сведения' : conditionsLabel[outcome]}
          minRows={2}
          onChange={(_event, payload) => setConditionsText(payload.value)}
          placeholder="По одному пункту в строке"
          value={conditionsText}
        />
        {showProblem && problem !== null ? (
          <p className={styles.companyError} role="alert">
            {problem}
          </p>
        ) : null}
        {record.isError ? (
          <p className={styles.companyError} role="alert">
            Решение не записано. {requestErrorMessage(record.error)}
          </p>
        ) : null}
        <div className={styles.detailActions}>
          <Button
            disabled={cannotRecord || record.isPending}
            onClick={() => {
              setShowProblem(true);
              if (problem === null && outcome !== null) record.mutate({
                outcome,
                rationale: rationale.trim(),
                conditions,
                company_ids: project.companies.map((company) => company.company_id),
                context_version: project.context_version,
                ...(artifact === undefined ? {} : {
                  based_on_artifact_id: artifact.id,
                  based_on_artifact_version: artifact.version,
                  evidence_refs: artifact.evidence_refs,
                }),
                ...(latest === undefined ? {} : { supersedes_id: latest.id }),
              });
            }}
            size={40}
            view="primary"
          >
            {record.isPending ? 'Записываем…' : 'Записать решение'}
          </Button>
          {record.isError ? (
            <Button onClick={() => { if (record.variables) record.mutate(record.variables); }} size={40} view="outlined">
              Повторить
            </Button>
          ) : null}
        </div>
        <p className={styles.decisionHint}>
          Решение записываете вы. Помощник его не принимает и не меняет; прежние решения
          сохраняются.
        </p>
      </section>
    </div>
  );
}
