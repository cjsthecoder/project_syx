/**
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * React application entry point.
 *
 * Mounts the root <App /> component into the #root DOM node using
 * ReactDOM.createRoot within React.StrictMode and loads global styles.
 */
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './pages/App'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)


