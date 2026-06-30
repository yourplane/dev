import { useCallback, useEffect, useRef, useState } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api } from './api'
import {
  draftIndicatesEditing,
  hasAnyAnswer,
  submittedAnswersEqual,
  submittedAnswersSignature,
  type QuestionAnswersDraft,
  type QuestionItem,
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
  const [selections, setSelections] = useState<Record<string, string>>({})
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
      setSelections(draft.selections ?? {})
      setFreeText(draft.freeText ?? {})
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
    const showEditable = draftIndicatesEditing(draft, questions)
    const nextLocked = !showEditable && !!persistedAnswers
    const nextSubmitted = persistedAnswers ?? null

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
      const answers = questions.map((q) => {
        const id = q.id ?? ''
        return {
          id,
          text: q.text,
          selected: selections[id] ?? '',
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
      {payload.intro.trim() ? (
        <div className="question-intro">
          <MarkdownInline>{payload.intro}</MarkdownInline>
        </div>
      ) : null}

      {questions.length === 0 ? (
        <p className="question-empty-notice">No questions from the agent</p>
      ) : locked ? (
        <div className="question-answers-summary">
          {questions.map((q) => (
            <QuestionSummary
              key={q.id}
              question={q}
              selected={displaySelections[q.id ?? ''] ?? ''}
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
              selected={selections[q.id ?? ''] ?? ''}
              freeText={freeText[q.id ?? ''] ?? ''}
              expanded={expandedFreeText[q.id ?? ''] ?? false}
              onSelect={(value) => {
                const id = q.id ?? ''
                setSelections((prev) => ({ ...prev, [id]: value }))
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
  onSelect,
  onFreeTextChange,
  onToggleFreeText,
}: {
  question: QuestionItem
  selected: string
  freeText: string
  expanded: boolean
  onSelect: (value: string) => void
  onFreeTextChange: (value: string) => void
  onToggleFreeText: () => void
}) {
  const qid = question.id ?? ''
  return (
    <fieldset className="question-field">
      <legend className="question-text">
        <MarkdownInline>{question.text}</MarkdownInline>
      </legend>
      {question.options.length > 0 ? (
        <div className="question-options" role="radiogroup" aria-label={question.text}>
          {question.options.map((option, i) => (
            <label key={`${qid}-${i}`} className="question-option">
              <input
                type="radio"
                name={`question-${qid}`}
                value={option}
                checked={selected === option}
                onChange={() => onSelect(option)}
              />
              <span className="question-option-label">
                <MarkdownInline>{option}</MarkdownInline>
              </span>
            </label>
          ))}
        </div>
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

function QuestionSummary({
  question,
  selected,
  freeText,
}: {
  question: QuestionItem
  selected: string
  freeText: string
}) {
  const hasSelected = selected.trim().length > 0
  const hasNotes = freeText.trim().length > 0
  if (!hasSelected && !hasNotes) return null
  return (
    <div className="question-summary-item">
      <div className="question-summary-text">
        <MarkdownInline>{question.text}</MarkdownInline>
      </div>
      {hasSelected ? (
        <p className="question-summary-selected">
          <strong>Selected:</strong>{' '}
          <MarkdownInline>{selected}</MarkdownInline>
        </p>
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
