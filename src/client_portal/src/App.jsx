import { Routes, Route } from 'react-router-dom'
import TaskSubmissionForm from './components/TaskSubmissionForm'
import TaskStatus from './components/TaskStatus'
import './App.css'

function App() {
  return (
    <div className="app">
      <header>
        <h1>AI Freelance Platform</h1>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<TaskSubmissionForm />} />
          <Route path="/task-status" element={<TaskStatus />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
