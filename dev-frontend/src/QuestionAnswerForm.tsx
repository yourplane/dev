import { useCallback, useEffect, useRef, useState } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api } from './api'
import {
  complexityLabel,
  draftIndicatesEditing,
  findOptionByLabel,
  hasAnyAnswer,
  isQuestionAnswered,
  normalizeSelectionsRecord,
  submittedAnswersEqual,
  submittedAnswersSignature,
  type QuestionAnswersDraft,
  type QuestionItem,
  type QuestionOption,
  type QuestionPayload,
  type SubmittedAnswers,
} from './questionForm'

const markdownComponents: Partial<Components> = {
  table: ({ children, ...props }) => (
    <div className="markdown-table-scroll">
      <table {...props}>{children}</table>
    </div>
  ),
}

function MarkdownInline({ children }: { children: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
      {children}
    </ReactMarkdown>
  )
}

export type { SubmittedAnswers }

const ARCHITECTURAL_IMPLICATIONS_LABEL = 'Architectural Implications'

function optionComplexityClass(complexity?: QuestionOption['complexity']): string {
  if (!complexity) return ''
  return `question-complexity-${complexity}`
}

function CollapsibleSection({
  label,
  children,
  defaultExpanded = false,
  className,
}: {
  label: string
  children: React.ReactNode
  defaultExpanded?: boolean
  className?: string
}) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  return (
    <div className={['question-collapsible', className].filter(Boolean).join(' ')}>
      <button
        type="button"
        className="question-collapsible-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((prev) => !prev)}
      >
        {label}
      </button>
      {expanded ? <div className="question-collapsible-body">{children}</div> : null}
    </div>
  )
}

export function QuestionAnswerForm({
  taskName,
  sourceFilename,
  payload,
  persistedAnswers,
  onSubmitted,
}: {
  taskName: string
  sourceFilename: string
  payload: QuestionPayload
  /** Latest submitted answers from feed, null if none, undefined while loading. */
  persistedAnswers?: SubmittedAnswers | null
  onSubmitted?: () => void
}) {
  const questions = payload.questions
  const [selections, setSelections] = useState<Record<string, string[]>>({})
  const [freeText, setFreeText] = useState<Record<string, string>>({})
  const [expandedFreeText, setExpandedFreeText] = useState<Record<string, boolean>>({})
  const [editing, setEditing] = useState(false)
  const [locked, setLocked] = useState(false)
  const [lastSubmitted, setLastSubmitted] = useState<SubmittedAnswers | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [draftStatus, setDraftStatus] = useState<'saved' | 'unsaved' | 'saving'>('saved')
  const draftLoadedRef = useRef(false)
  const lockStateAppliedRef = useRef(false)
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const persistedAnswersSignatureValue = submittedAnswersSignature(persistedAnswers)

  useEffect(() => {
    draftLoadedRef.current = false
    lockStateAppliedRef.current = false
    let cancelled = false
    api.getQuestionAnswersDraft(taskName, sourceFilename).then((draft) => {
      if (cancelled) return
      setSelections((prev) => (
        Object.keys(prev).length > 0 ? prev : normalizeSelectionsRecord(draft.selections)
      ))
      setFreeText((prev) => (
        Object.keys(prev).length > 0 ? prev : (draft.freeText ?? {})
      ))
      setExpandedFreeText(draft.expandedFreeText ?? {})
      setEditing(draft.editing ?? false)
      draftLoadedRef.current = true
      setDraftStatus('saved')
    }).catch(() => {
      draftLoadedRef.current = true
    })
    return () => { cancelled = true }
  }, [taskName, sourceFilename])

  useEffect(() => {
    if (!draftLoadedRef.current) return
    if (persistedAnswers === undefined) return

    const draft: QuestionAnswersDraft = {
      selections,
      freeText,
      expandedFreeText,
      editing,
    }
    const effectiveAnswers = persistedAnswers ?? (lastSubmitted && !editing ? lastSubmitted : null)
    const showEditable = editing || (!effectiveAnswers && draftIndicatesEditing(draft, questions))
    const nextLocked = !showEditable && !!effectiveAnswers
    const nextSubmitted = effectiveAnswers

    if (!lockStateAppliedRef.current) {
      lockStateAppliedRef.current = true
      setLocked(nextLocked)
      setLastSubmitted(nextSubmitted)
      return
    }

    setLocked((prev) => (prev === nextLocked ? prev : nextLocked))
    setLastSubmitted((prev) => (
      submittedAnswersEqual(prev, nextSubmitted) ? prev : nextSubmitted
    ))
  }, [
    persistedAnswersSignatureValue,
    persistedAnswers,
    selections,
    freeText,
    expandedFreeText,
    editing,
    questions,
  ])

  const saveDraft = useCallback((data: QuestionAnswersDraft) => {
    if (!draftLoadedRef.current) return
    setDraftStatus('unsaved')
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(() => {
      setDraftStatus('saving')
      api.setQuestionAnswersDraft(taskName, sourceFilename, data)
        .then(() => setDraftStatus('saved'))
        .catch(() => setDraftStatus('unsaved'))
    }, 400)
  }, [taskName, sourceFilename])

  useEffect(() => {
    if (!draftLoadedRef.current || locked) return
    saveDraft({ selections, freeText, expandedFreeText, editing: editing || undefined })
  }, [selections, freeText, expandedFreeText, editing, locked, saveDraft])

  const canSubmit = !locked && hasAnyAnswer(questions, selections, freeText)

  const handleSubmit = async () => {
    if (!canSubmit) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const answers = questions
        .filter((q) => isQuestionAnswered(q, selections, freeText))
        .map((q) => {
          const id = q.id ?? ''
          return {
            id,
            text: q.text,
            selected: selections[id] ?? [],
            free_text: freeText[id] ?? '',
          }
        })
      await api.postQuestionAnswers(taskName, { source: sourceFilename, answers })
      const submitted: SubmittedAnswers = {
        selections: { ...selections },
        freeText: { ...freeText },
      }
      setLastSubmitted(submitted)
      setEditing(false)
      setLocked(true)
      setDraftStatus('saved')
      api.setQuestionAnswersDraft(taskName, sourceFilename, {
        selections: {},
        freeText: {},
        expandedFreeText: {},
      }).catch(() => {})
      onSubmitted?.()
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  const handleUnlock = () => {
    const nextSelections = lastSubmitted
      ? { ...lastSubmitted.selections }
      : { ...selections }
    const nextFreeText = lastSubmitted
      ? { ...lastSubmitted.freeText }
      : { ...freeText }
    setSelections(nextSelections)
    setFreeText(nextFreeText)
    setEditing(true)
    setLocked(false)
    if (draftLoadedRef.current) {
      void api.setQuestionAnswersDraft(taskName, sourceFilename, {
        selections: nextSelections,
        freeText: nextFreeText,
        expandedFreeText,
        editing: true,
      })
    }
  }

  const displaySelections = locked && lastSubmitted ? lastSubmitted.selections : selections
  const displayFreeText = locked && lastSubmitted ? lastSubmitted.freeText : freeText

  return (
    <div className="question-answer-form">
      {payload.response?.trim() ? (
        <div className="question-response">
          <MarkdownInline>{payload.response}</MarkdownInline>
        </div>
      ) : null}

      {payload.summary?.trim() ? (
        <CollapsibleSection label="Summary" className="question-summary-block">
          <MarkdownInline>{payload.summary}</MarkdownInline>
        </CollapsibleSection>
      ) : null}

      {questions.length === 0 ? (
        <p className="question-empty-notice">No questions from the agent</p>
      ) : locked ? (
        <div className="question-answers-summary">
          {questions.map((q) => (
            <QuestionSummary
              key={q.id}
              question={q}
              selected={displaySelections[q.id ?? ''] ?? []}
              freeText={displayFreeText[q.id ?? ''] ?? ''}
            />
          ))}
          <button type="button" className="question-unlock-btn" onClick={handleUnlock}>
            Unlock to edit
          </button>
        </div>
      ) : (
        <>
          {questions.map((q) => (
            <QuestionField
              key={q.id}
              question={q}
              selected={selections[q.id ?? ''] ?? []}
              freeText={freeText[q.id ?? ''] ?? ''}
              expanded={expandedFreeText[q.id ?? ''] ?? false}
              onSelectSingle={(value) => {
                const id = q.id ?? ''
                setSelections((prev) => ({ ...prev, [id]: value ? [value] : [] }))
              }}
              onToggleMulti={(value) => {
                const id = q.id ?? ''
                setSelections((prev) => {
                  const current = prev[id] ?? []
                  const next = current.includes(value)
                    ? current.filter((item) => item !== value)
                    : [...current, value]
                  return { ...prev, [id]: next }
                })
              }}
              onFreeTextChange={(value) => {
                const id = q.id ?? ''
                setFreeText((prev) => ({ ...prev, [id]: value }))
              }}
              onToggleFreeText={() => {
                const id = q.id ?? ''
                setExpandedFreeText((prev) => ({ ...prev, [id]: !prev[id] }))
              }}
            />
          ))}
          <div className="question-form-actions">
            <button
              type="button"
              className="question-submit-btn"
              disabled={!canSubmit || submitting}
              onClick={() => void handleSubmit()}
            >
              {submitting ? 'Submitting…' : 'Submit answers'}
            </button>
            <span className={`draft-status draft-status-${draftStatus}`} role="status">
              {draftStatus === 'saved' && 'Draft saved'}
              {draftStatus === 'unsaved' && 'Unsaved draft'}
              {draftStatus === 'saving' && 'Saving draft…'}
            </span>
          </div>
          {submitError ? <p className="inline-error">{submitError}</p> : null}
        </>
      )}
    </div>
  )
}

function QuestionField({
  question,
  selected,
  freeText,
  expanded,
  onSelectSingle,
  onToggleMulti,
  onFreeTextChange,
  onToggleFreeText,
}: {
  question: QuestionItem
  selected: string[]
  freeText: string
  expanded: boolean
  onSelectSingle: (value: string) => void
  onToggleMulti: (value: string) => void
  onFreeTextChange: (value: string) => void
  onToggleFreeText: () => void
}) {
  const qid = question.id ?? ''
  const isMultiple = question.multiple === true
  const singleSelected = selected[0] ?? ''
  return (
    <fieldset className="question-field">
      <legend className="question-text">
        <span className="question-text-content">
          <MarkdownInline>{question.text}</MarkdownInline>
        </span>
        {question.examples?.trim() ? (
          <CollapsibleSection label="Examples" className="question-attached-collapsible">
            <MarkdownInline>{question.examples}</MarkdownInline>
          </CollapsibleSection>
        ) : null}
      </legend>
      {question.options.length > 0 ? (
        isMultiple ? (
          <div className="question-options" role="group" aria-label={question.text}>
            {question.options.map((option, i) => (
              <label
                key={`${qid}-${i}`}
                className={['question-option', optionComplexityClass(option.complexity)].filter(Boolean).join(' ')}
                title={option.complexity ? complexityLabel(option.complexity) : undefined}
              >
                <input
                  type="checkbox"
                  name={`question-${qid}`}
                  value={option.label}
                  checked={selected.includes(option.label)}
                  onChange={() => onToggleMulti(option.label)}
                />
                <OptionContent option={option} />
              </label>
            ))}
          </div>
        ) : (
          <div className="question-options" role="radiogroup" aria-label={question.text}>
            {question.options.map((option, i) => {
              const isSelected = singleSelected === option.label
              return (
                <div
                  key={`${qid}-${i}`}
                  className={['question-option', optionComplexityClass(option.complexity)].filter(Boolean).join(' ')}
                  title={option.complexity ? complexityLabel(option.complexity) : undefined}
                >
                  <label className="question-option-label-wrap">
                    <input
                      type="radio"
                      name={`question-${qid}`}
                      value={option.label}
                      checked={isSelected}
                      onChange={() => onSelectSingle(option.label)}
                    />
                    <OptionContent option={option} />
                  </label>
                  {isSelected ? (
                    <button
                      type="button"
                      className="question-option-clear"
                      aria-label="Clear selection"
                      title="Clear selection"
                      onClick={() => onSelectSingle('')}
                    >
                      ×
                    </button>
                  ) : null}
                </div>
              )
            })}
          </div>
        )
      ) : null}
      {!expanded ? (
        <button type="button" className="question-add-notes-btn" onClick={onToggleFreeText}>
          Add additional notes
        </button>
      ) : (
        <div className="question-free-text">
          <label htmlFor={`free-${qid}`}>Additional notes</label>
          <textarea
            id={`free-${qid}`}
            value={freeText}
            onChange={(e) => onFreeTextChange(e.target.value)}
            rows={3}
          />
        </div>
      )}
    </fieldset>
  )
}

function OptionContent({ option }: { option: QuestionOption }) {
  return (
    <span className="question-option-content">
      <span className="question-option-group">
        <span className="question-option-label">
          <MarkdownInline>{option.label}</MarkdownInline>
        </span>
        {option.implications?.trim() ? (
          <CollapsibleSection
            label={ARCHITECTURAL_IMPLICATIONS_LABEL}
            className="question-attached-collapsible question-option-implications"
          >
            <MarkdownInline>{option.implications}</MarkdownInline>
          </CollapsibleSection>
        ) : null}
      </span>
    </span>
  )
}

function QuestionSummary({
  question,
  selected,
  freeText,
}: {
  question: QuestionItem
  selected: string[]
  freeText: string
}) {
  const hasSelected = selected.length > 0
  const hasNotes = freeText.trim().length > 0
  if (!hasSelected && !hasNotes) return null
  return (
    <div className="question-summary-item">
      <div className="question-summary-header">
        <div className="question-summary-text">
          <MarkdownInline>{question.text}</MarkdownInline>
        </div>
        {question.examples?.trim() ? (
          <CollapsibleSection label="Examples" className="question-attached-collapsible">
            <MarkdownInline>{question.examples}</MarkdownInline>
          </CollapsibleSection>
        ) : null}
      </div>
      {hasSelected ? (
        <div className="question-summary-selected">
          {selected.map((label) => {
            const selectedOption = findOptionByLabel(question.options, label)
            return (
              <div
                key={label}
                className={[
                  'question-summary-selection-group',
                  optionComplexityClass(selectedOption?.complexity),
                ].filter(Boolean).join(' ')}
                title={selectedOption?.complexity ? complexityLabel(selectedOption.complexity) : undefined}
              >
                <div className="question-summary-selection-row">
                  <strong>Selected:</strong>{' '}
                  <span className="question-summary-selected-label">
                    <MarkdownInline>{label}</MarkdownInline>
                  </span>
                </div>
                {selectedOption?.implications?.trim() ? (
                  <CollapsibleSection
                    label={ARCHITECTURAL_IMPLICATIONS_LABEL}
                    className="question-attached-collapsible question-option-implications"
                  >
                    <MarkdownInline>{selectedOption.implications}</MarkdownInline>
                  </CollapsibleSection>
                ) : null}
              </div>
            )
          })}
        </div>
      ) : null}
      {hasNotes ? (
        <div className="question-summary-notes">
          <strong>Additional notes:</strong>
          <MarkdownInline>{freeText}</MarkdownInline>
        </div>
      ) : null}
    </div>
  )
}
