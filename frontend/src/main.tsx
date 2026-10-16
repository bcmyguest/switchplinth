import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { applyTheme } from './theme'
import './styles.css'
import './repository.css'
import './correction.css'
import '@xyflow/react/dist/style.css'
import './readability.css'
import './map-readability.css'

applyTheme()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><App /></React.StrictMode>,
)
