import type { TaskListStatus } from './api'

export const TASK_STATUS_LABELS: Record<Exclude<TaskListStatus, 'idle'>, string> = {
  worker_issue: 'Worker offline',
  syncing: 'Command syncing — waiting for worker',
  running: 'Command in progress',
  failed: 'Last command failed',
  waiting_for_answers: 'Waiting for question answers',
  ready_for_next_step: 'Ready for next step (e.g. Plan or Implement)',
  plan_complete: 'Plan complete',
  implement_complete: 'Implement complete',
  merge_from_main_complete: 'Merge from main complete',
  user_comment: 'User comment — latest activity is your input',
  pr_comments: 'PR comments — latest activity is review feedback',
  bash_complete: 'Shell command finished — latest activity is bash output',
}

const ACTIVE_STATUSES = new Set<TaskListStatus>(['running', 'syncing'])

const COMPLETION_STATUSES = new Set<TaskListStatus>([
  'waiting_for_answers',
  'ready_for_next_step',
  'plan_complete',
  'implement_complete',
  'merge_from_main_complete',
  'bash_complete',
  'failed',
])

export function isActiveTaskStatus(status: TaskListStatus): boolean {
  return ACTIVE_STATUSES.has(status)
}

export function isCompletionTransition(prev: TaskListStatus, next: TaskListStatus): boolean {
  if (!isActiveTaskStatus(prev)) return false
  if (next === 'idle') return true
  return COMPLETION_STATUSES.has(next)
}

export function completionStatusLabel(status: TaskListStatus): string {
  if (status === 'idle') return 'Command finished'
  if (status in TASK_STATUS_LABELS) {
    return TASK_STATUS_LABELS[status as Exclude<TaskListStatus, 'idle'>]
  }
  return 'Command finished'
}

export function completionNotificationTitle(taskName: string, status: TaskListStatus): string {
  return `Task ${taskName} — ${completionStatusLabel(status)}`
}
