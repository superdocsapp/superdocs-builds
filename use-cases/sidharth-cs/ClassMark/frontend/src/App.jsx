import { useEffect, useState } from 'react'
import { api, ApiError } from './api.js'
import { countDecisions } from './lib/text.js'
import { DEFAULT_REVIEW_DEPTH, DEFAULT_REVIEW_MODE } from './lib/reviewConfig.js'
import AppHeader from './components/AppHeader.jsx'
import LoginScreen from './components/LoginScreen.jsx'
import SelectorList from './components/SelectorList.jsx'
import { Breadcrumb, WorkflowStepper } from './components/StepIndicator.jsx'
import ErrorBanner from './components/ErrorBanner.jsx'
import TechnicalDetails from './components/TechnicalDetails.jsx'
import ReviewInstruction from './components/ReviewInstruction.jsx'
import ReviewChangeCard from './components/ReviewChangeCard.jsx'
import {
  ReviewSummary,
  NoChangesState,
  ExportPanel,
  DownloadPanel,
  DriveUploadPanel,
  AttachPanel,
  ReturnPanel,
  VerifyPanel,
  FinalSuccess,
  TerminalState,
} from './components/Panels.jsx'

// Backend-authoritative state: every step action posts to the backend and
// the returned WorkflowData snapshot is the single source of truth. The
// UI never optimistically mutates workflow state.

const SUBMISSION_STATE_LABELS = {
  TURNED_IN: 'Turned in',
  RETURNED: 'Returned',
  NEW: 'Assigned',
  CREATED: 'Assigned',
  RECLAIMED_BY_STUDENT: 'Reclaimed',
}

function submissionStateLabel(state) {
  return SUBMISSION_STATE_LABELS[state] || state || 'Unknown'
}

const DOWNLOADABLE = ['exported', 'drive_uploaded', 'attached', 'returned', 'verified']

export default function App() {
  const [auth, setAuth] = useState(null) // null = loading
  const [authError, setAuthError] = useState(null)

  // wizard selections
  const [courses, setCourses] = useState([])
  const [course, setCourse] = useState(null)
  const [assignments, setAssignments] = useState([])
  const [assignment, setAssignment] = useState(null)
  const [submissions, setSubmissions] = useState([])
  const [loading, setLoading] = useState(null) // "courses" | "assignments" | "submissions" | null

  // workflow
  const [workflow, setWorkflow] = useState(null)
  const [workflowId, setWorkflowId] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [reviewMode, setReviewMode] = useState(DEFAULT_REVIEW_MODE)
  const [reviewDepth, setReviewDepth] = useState(DEFAULT_REVIEW_DEPTH)
  const [additionalInstructions, setAdditionalInstructions] = useState('')

  useEffect(() => {
    api('/api/auth/status')
      .then(setAuth)
      .catch((e) => setAuthError(String(e)))
  }, [])

  // Resume an in-flight workflow across a refresh (the backend registry
  // survives; only the browser lost the workflow id). This is the
  // duplicate-safety anchor: a refresh does NOT start a second review of
  // the same submission. Gated on an authenticated session so a signed-out
  // or different user never picks up another session's workflow.
  useEffect(() => {
    const saved = localStorage.getItem('classroom_workflow_id')
    if (!auth?.authenticated || !saved || workflow) return
    api(`/api/workflow/${saved}/state`)
      .then((data) => {
        setWorkflowId(saved)
        setWorkflow(data)
      })
      .catch((e) => {
        localStorage.removeItem('classroom_workflow_id')
        if (e instanceof ApiError && e.status === 403) return // someone else's workflow
        setError(
          'This workflow expired after the server restarted. Start a new review.'
        )
      })
  }, [workflow, auth])

  // ---- selection -----------------------------------------------------------

  async function loadCourses() {
    setError(null)
    setLoading('courses')
    try {
      setCourses(await api('/api/classroom/courses'))
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(null)
    }
  }

  async function selectCourse(c) {
    setError(null)
    setCourse(c)
    setAssignment(null)
    setAssignments([])
    setSubmissions([])
    setLoading('assignments')
    try {
      setAssignments(await api(`/api/classroom/courses/${c.id}/coursework`))
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(null)
    }
  }

  async function selectAssignment(a) {
    setError(null)
    setAssignment(a)
    setSubmissions([])
    setLoading('submissions')
    try {
      setSubmissions(
        await api(`/api/classroom/courses/${course.id}/coursework/${a.id}/submissions`)
      )
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(null)
    }
  }

  async function startReview(sub) {
    setError(null)
    setBusy(true)
    try {
      const data = await api('/api/workflow/start', {
        method: 'POST',
        body: JSON.stringify({
          course_id: course.id,
          course_name: course.name,
          coursework_id: assignment.id,
          assignment_title: assignment.title,
          submission_id: sub.id,
        }),
      })
      setWorkflowId(data.workflow_id)
      localStorage.setItem('classroom_workflow_id', data.workflow_id)
      setWorkflow(data)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  // ---- workflow step actions ----------------------------------------------

  async function step(path, body) {
    setBusy(true)
    setError(null)
    try {
      setWorkflow(
        await api(`/api/workflow/${workflowId}${path}`, {
          method: 'POST',
          ...(body ? { body: JSON.stringify(body) } : {}),
        })
      )
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function decide(chunkId, decision) {
    setBusy(true)
    setError(null)
    try {
      setWorkflow(
        await api(`/api/workflow/${workflowId}/decide`, {
          method: 'POST',
          body: JSON.stringify({ chunk_id: chunkId, decision }),
        })
      )
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function startReviewJob() {
    await step('/upload')
    await step('/review', {
      mode: reviewMode,
      depth: reviewDepth,
      additional_instructions: additionalInstructions,
    })
  }

  function resetAll() {
    localStorage.removeItem('classroom_workflow_id')
    setWorkflow(null)
    setWorkflowId(null)
    setCourse(null)
    setAssignment(null)
    setSubmissions([])
    setReviewMode(DEFAULT_REVIEW_MODE)
    setReviewDepth(DEFAULT_REVIEW_DEPTH)
    setAdditionalInstructions('')
  }

  async function signOut() {
    try {
      await api('/api/auth/logout', { method: 'POST' })
    } catch (e) {
      // Clear local state either way; the server session may already be gone.
    }
    // Workflow resume state is bound to this authenticated session; it must
    // not survive into a different user's session.
    localStorage.removeItem('classroom_workflow_id')
    setWorkflow(null)
    setWorkflowId(null)
    setCourse(null)
    setAssignment(null)
    setSubmissions([])
    setAuth(null)
    window.location.reload()
  }

  // ---- screens -------------------------------------------------------------

  if (auth === null) {
    return <div className="boot-screen">Classmark</div>
  }

  if (!auth.authenticated) {
    return <LoginScreen error={authError} />
  }

  const downloadHref = workflowId ? `/api/workflow/${workflowId}/export/download` : null

  return (
    <div className="app-shell">
      <AppHeader email={auth.email} onSignOut={signOut} busy={busy} />

      <main className="app-main">
        {error && (
          <ErrorBanner
            title="Something needs your attention"
            message={error}
            onRetry={workflow ? () => setError(null) : undefined}
            retryLabel="Dismiss"
          />
        )}

        {!workflow && (
          <section className="wizard">
            <Breadcrumb
              crumbs={[
                { label: 'Course', active: !course },
                { label: 'Assignment', active: !!course && !assignment },
                { label: 'Submission', active: !!course && !!assignment },
              ]}
            />

            {!course && (
              <SelectorList
                title="Select a course"
                subtitle="Choose the course with the submission you want to review."
                items={courses}
                loading={loading === 'courses'}
                onRetry={loadCourses}
                emptyMessage="No active courses found for this account."
                renderItem={(c) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      className="selector-item"
                      onClick={() => selectCourse(c)}
                      disabled={loading !== null}
                    >
                      <span className="selector-title">{c.name}</span>
                      {c.section && <span className="selector-meta">{c.section}</span>}
                      <span className="selector-arrow" aria-hidden="true">→</span>
                    </button>
                  </li>
                )}
              />
            )}

            {course && !assignment && (
              <>
                <div className="row-between">
                  <SelectorList
                    title="Select an assignment"
                    subtitle={course.name}
                    items={assignments}
                    loading={loading === 'assignments'}
                    onRetry={() => selectCourse(course)}
                    emptyMessage="No assignments in this course."
                    renderItem={(a) => (
                      <li key={a.id}>
                        <button
                          type="button"
                          className="selector-item"
                          onClick={() => selectAssignment(a)}
                          disabled={loading !== null}
                        >
                          <span className="selector-title">{a.title}</span>
                          <span className="selector-meta">
                            {a.state === 'PUBLISHED' ? 'Published' : a.state}
                          </span>
                          <span className="selector-arrow" aria-hidden="true">→</span>
                        </button>
                      </li>
                    )}
                  />
                  <button type="button" className="btn btn-ghost btn-sm back-btn" onClick={() => setCourse(null)}>
                    ← Back
                  </button>
                </div>
              </>
            )}

            {course && assignment && (
              <>
                <SelectorList
                  title="Select a student submission"
                  subtitle={`${course.name} › ${assignment.title}`}
                  items={submissions}
                  loading={loading === 'submissions'}
                  onRetry={() => selectAssignment(assignment)}
                  emptyMessage="No student submissions yet."
                  renderItem={(s) => {
                    const file = s.attachments?.find((a) => a.driveFile)?.driveFile
                    return (
                      <li key={s.id}>
                        <button
                          type="button"
                          className="selector-item"
                          onClick={() => startReview(s)}
                          disabled={busy}
                        >
                          <span className="selector-title">
                            Student {String(s.userId || s.id).slice(-4)}
                          </span>
                          <span className={`state-pill state-${s.state}`}>
                            {submissionStateLabel(s.state)}
                          </span>
                          {file && <span className="file-tag">{file.title}</span>}
                          <span className="selector-arrow" aria-hidden="true">→</span>
                        </button>
                      </li>
                    )
                  }}
                />
                <button type="button" className="btn btn-ghost btn-sm back-btn" onClick={() => setAssignment(null)}>
                  ← Back
                </button>
              </>
            )}
          </section>
        )}

        {workflow && (
          <section className="workflow">
            <div className="workflow-head">
              <h2>{workflow.assignment_title || 'Student submission review'}</h2>
              <p className="workflow-doc">{workflow.original_filename || 'document'}</p>
            </div>

            <dl className="identity-strip">
              <div><dt>Course</dt><dd>{workflow.course_name || workflow.course_id}</dd></div>
              <div><dt>Assignment</dt><dd>{workflow.assignment_title || workflow.coursework_id}</dd></div>
              <div><dt>Student</dt><dd>Student {String(workflow.student_user_id || workflow.submission_id).slice(-4)}</dd></div>
            </dl>

            <WorkflowStepper state={workflow.state} />

            <TechnicalDetails
              rows={{
                'Submission ID': workflow.submission_id,
                'Course ID': workflow.course_id,
                'Assignment ID': workflow.coursework_id,
                'Original file ID': workflow.original_drive_file_id,
                'Reviewed file ID': workflow.reviewed_drive_file_id,
                'SuperDocs session': workflow.superdocs_session_id,
              }}
            />

            {/* Review instruction (before the review starts) */}
            {workflow.state === 'document_retrieved' && (
              <ReviewInstruction
                mode={reviewMode}
                depth={reviewDepth}
                additionalInstructions={additionalInstructions}
                onModeChange={setReviewMode}
                onDepthChange={setReviewDepth}
                onAdditionalInstructionsChange={setAdditionalInstructions}
                onStart={startReviewJob}
                busy={busy}
              />
            )}

            {/* Review completed with NO proposed changes — honest dead end */}
            {workflow.state === 'review_generated' && (
              <NoChangesState onReset={resetAll} />
            )}

            {/* HITL review screen */}
            {workflow.state === 'awaiting_approval' && (
              <div className="panel">
                <h3 className="panel-title">Proposed changes</h3>
                <ul className="change-list">
                  {workflow.pending_changes.map((c, i) => (
                    <ReviewChangeCard key={c.chunk_id} change={c} index={i} onDecide={decide} busy={busy} />
                  ))}
                </ul>
                <ReviewSummary
                  counts={countDecisions(workflow.pending_changes)}
                  onSubmit={() => step('/submit-approval')}
                  busy={busy}
                />
              </div>
            )}

            {/* Post-approval chain */}
            {workflow.state === 'approval_complete' && (
              <ExportPanel busy={busy} onExport={() => step('/export')} />
            )}
            {DOWNLOADABLE.includes(workflow.state) && (
              <DownloadPanel filename={workflow.reviewed_filename || 'reviewed.docx'} downloadHref={downloadHref} />
            )}
            {workflow.state === 'exported' && (
              <DriveUploadPanel busy={busy} onUpload={() => step('/upload-drive')} filename={workflow.reviewed_filename} />
            )}
            {workflow.state === 'drive_uploaded' && (
              <AttachPanel
                busy={busy}
                onAttach={() => step('/attach')}
                filename={workflow.reviewed_filename}
                assignmentTitle={workflow.assignment_title}
              />
            )}
            {workflow.state === 'attached' && (
              <ReturnPanel busy={busy} onReturn={() => step('/return')} />
            )}
            {workflow.state === 'returned' && (
              <VerifyPanel busy={busy} onVerify={() => step('/verify')} />
            )}

            {/* Final success */}
            {workflow.state === 'verified' && (
              <FinalSuccess
                workflow={workflow}
                onReset={resetAll}
                downloadHref={downloadHref}
                filename={workflow.reviewed_filename}
              />
            )}

            {/* Terminal: blocked or error */}
            {(workflow.state === 'blocked' || workflow.state === 'error') && (
              <TerminalState workflow={workflow} onReset={resetAll} />
            )}
          </section>
        )}
      </main>
    </div>
  )
}
