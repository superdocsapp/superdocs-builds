import { Routes, Route } from 'react-router-dom'
import { ReviewPage } from '@/pages/ReviewPage'
import { PipelineCanvas } from '@/pages/PipelineCanvas'
import { LandingPage } from '@/pages/LandingPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/pipeline" element={<PipelineCanvas />} />
      <Route path="/review" element={<ReviewPage />} />
    </Routes>
  )
}

export default App
