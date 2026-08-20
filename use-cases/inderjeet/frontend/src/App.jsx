import React, { useState, useEffect } from 'react'
import DocumentDiff from './components/DocumentDiff'
import ReviewCard from './components/ReviewCard'
import { AlertTriangle, ShieldCheck, Coins, RefreshCw } from 'lucide-react'

export default function App() {
  const [batchId, setBatchId] = useState('batch_101')
  const [batchStatus, setBatchStatus] = useState('INGESTED')
  const [travelers, setTravelers] = useState([])
  const [selectedTravelerId, setSelectedTravelerId] = useState(null)
  const [logs, setLogs] = useState([])
  const [stats, setStats] = useState({ cost: 0.00, operations: 0 })
  const [isRunning, setIsRunning] = useState(false)

  // Initialize traveler data
  useEffect(() => {
    setTravelers([
      {
        id: 'trav_1',
        passenger_name: 'Alice Johnson',
        email: 'alice@johnson.com',
        language: 'en',
        loyalty_status: 'GOLD',
        original_itinerary: 'Flight AA123 London to Madrid, departs 10:00 AM on 20th August.',
        proposed_itinerary: 'Flight AA456 London to Madrid, departs 2:30 PM on 20th August.',
        explanation_letter: 'Dear Alice Johnson,\n\nWe regret to inform you that your flight AA123 has been cancelled. We have re-accommodated you on flight AA456. Your updated itinerary is attached.\n\nBest regards,\nTravel Operations Team',
        voucher_status: 'ELIGIBLE',
        approval_status: 'PENDING'
      },
      {
        id: 'trav_2',
        passenger_name: 'Carlos Gomez',
        email: 'carlos@gomez.es',
        language: 'es',
        loyalty_status: 'PLATINUM',
        original_itinerary: 'Flight AA123 London to Madrid, departs 10:00 AM on 20th August.',
        proposed_itinerary: 'Flight AA456 London to Madrid, departs 2:30 PM on 20th August.',
        explanation_letter: 'Estimado Carlos Gomez,\n\nLamentamos informarle que su vuelo AA123 ha sido cancelado. Le hemos reubicado en el vuelo AA456. Adjuntamos su itinerario actualizado.\n\nAtentamente,\nEquipo de Operaciones de Viaje',
        voucher_status: 'ELIGIBLE',
        approval_status: 'PENDING'
      },
      {
        id: 'trav_3',
        passenger_name: 'Unaffected Traveler',
        email: 'unaffected@traveler.com',
        language: 'en',
        loyalty_status: 'STANDARD',
        original_itinerary: 'Flight BA789 London to Tokyo, departs 11:00 AM on 25th August.',
        proposed_itinerary: 'Flight BA789 London to Tokyo, departs 11:00 AM on 25th August.',
        explanation_letter: '',
        voucher_status: 'INELIGIBLE',
        approval_status: 'PENDING'
      }
    ])
    setLogs([
      { stage: 'INGESTION', message: 'Ingested manifest contains 3 travelers.' }
    ])
  }, [])

  const startBatchRun = () => {
    setIsRunning(true)
    setBatchStatus('PROCESSING')
    
    // Simulate LangGraph processing stages
    setTimeout(() => {
      setLogs(prev => [...prev, { stage: 'ANALYSIS', message: 'Impact analysis parsed. Flagged 2 passengers affected by Flight AA123 cancellation.' }])
      setBatchStatus('IMPACT_ANALYZED')
    }, 1000)

    setTimeout(() => {
      setLogs(prev => [...prev, { stage: 'SURGERY', message: 'Completed surgical edit updates via SuperDocs API client.' }])
      setStats({ cost: 0.10, operations: 2 })
    }, 2000)

    setTimeout(() => {
      setLogs(prev => [...prev, { stage: 'DRAFTING', message: 'Drafted 2 localized explanation letters & initialized vouchers.' }])
      setBatchStatus('PENDING_APPROVAL')
      setIsRunning(false)
      setSelectedTravelerId('trav_1') // Auto-select first traveler for review
    }, 3000)
  }

  const handleDecision = (travelerId, status, letterText) => {
    setTravelers(prev => prev.map(t => {
      if (t.id === travelerId) {
        return { ...t, approval_status: status, explanation_letter: letterText }
      }
      return t
    }))
    
    setLogs(prev => [...prev, { stage: 'REVIEW', message: `Passenger ${travelerId} set to ${status}.` }])
  }

  const commitBatch = () => {
    setBatchStatus('COMMITTED')
    setLogs(prev => [...prev, { stage: 'COMMIT', message: 'All approved traveler packages compiled, finalized, and exported successfully.' }])
  }

  const selectedTraveler = travelers.find(t => t.id === selectedTravelerId)

  return (
    <div className="app-container">
      <div className="header">
        <div>
          <h1 className="title">Disruption Re-Issue Engine</h1>
          <span style={{ color: 'var(--text-secondary)' }}>Batch Reference: {batchId}</span>
        </div>
        <div>
          {batchStatus === 'INGESTED' && (
            <button className="button" onClick={startBatchRun}>
              Start Disruption processing Run
            </button>
          )}
          {batchStatus === 'PENDING_APPROVAL' && (
            <button className="button button-success" onClick={commitBatch}>
              Commit & Export Finalized batch
            </button>
          )}
          <span style={{ marginLeft: '1rem' }} className="badge badge-pending">
            {batchStatus}
          </span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 2fr 1fr', gap: '1.5rem' }}>
        
        {/* Left Side: Travelers manifest selection list */}
        <div>
          <h2>Manifest</h2>
          {travelers.map(t => (
            <div 
              key={t.id} 
              className="card" 
              style={{ border: selectedTravelerId === t.id ? '2px solid var(--primary-color)' : '1px solid var(--border-color)', cursor: 'pointer', padding: '1rem', marginBottom: '0.75rem' }}
              onClick={() => setSelectedTravelerId(t.id)}
            >
              <strong>{t.passenger_name}</strong>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '0.5rem', fontSize: '0.85rem' }}>
                <span className={`badge badge-${t.approval_status.toLowerCase()}`}>
                  {t.approval_status}
                </span>
                <span style={{ color: 'var(--text-secondary)' }}>
                  {t.voucher_status === 'ELIGIBLE' ? 'Voucher entitlement' : 'No Voucher'}
                </span>
              </div>
            </div>
          ))}
        </div>

        {/* Center: Selected Traveler Detail (Diff and Correspondence card) */}
        <div>
          <h2>Review & Adjustments</h2>
          {selectedTraveler ? (
            <div>
              {selectedTraveler.id !== 'trav_3' ? (
                <>
                  <DocumentDiff 
                    original={selectedTraveler.original_itinerary} 
                    proposed={selectedTraveler.proposed_itinerary} 
                  />
                  <ReviewCard 
                    traveler={selectedTraveler} 
                    onDecision={handleDecision} 
                  />
                </>
              ) : (
                <div className="card" style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                  <ShieldCheck size={40} color="var(--success-color)" />
                  <div>
                    <h3 style={{ margin: 0 }}>Unaffected Passenger</h3>
                    <p style={{ margin: '0.25rem 0 0 0', color: 'var(--text-secondary)' }}>
                      No segment matches disruption coordinates. Original itinerary remains identical.
                    </p>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="card" style={{ textAlign: 'center', padding: '3rem' }}>
              <AlertTriangle style={{ margin: '0 auto 1rem auto', display: 'block', color: 'var(--warning-color)' }} size={48} />
              <h3>Select a Traveler to Start Review</h3>
              <p style={{ color: 'var(--text-secondary)' }}>
                You must trigger the process run first, then inspect and approve each traveler manifest.
              </p>
            </div>
          )}
        </div>

        {/* Right Side: Audit Logs & Cost Metrics */}
        <div>
          <h2>Operations</h2>
          <div className="card" style={{ padding: '1rem' }}>
            <h4 style={{ margin: '0 0 1rem 0' }}>Cost & Tokens Ledger</h4>
            <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', marginBottom: '1rem' }}>
              <Coins color="var(--warning-color)" />
              <div>
                <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Cost (Est. USD)</span>
                <div style={{ fontSize: '1.2rem', fontWeight: 'bold' }}>${stats.cost.toFixed(2)}</div>
              </div>
            </div>
            <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
              <RefreshCw color="var(--primary-color)" />
              <div>
                <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>SuperDocs Ops</span>
                <div style={{ fontSize: '1.2rem', fontWeight: 'bold' }}>{stats.operations} / 50</div>
              </div>
            </div>
          </div>

          <div className="card" style={{ padding: '1rem', maxHeight: '300px', overflowY: 'auto' }}>
            <h4 style={{ margin: '0 0 1rem 0' }}>Execution Logs</h4>
            {logs.map((log, i) => (
              <div key={i} style={{ marginBottom: '0.75rem', fontSize: '0.85rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.5rem' }}>
                <span style={{ fontWeight: 600, color: 'var(--primary-color)' }}>[{log.stage}] </span>
                <span style={{ color: 'var(--text-secondary)' }}>{log.message}</span>
              </div>
            ))}
          </div>
        </div>

      </div>
    </div>
  )
}
