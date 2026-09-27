import React from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './App';
import './chanx-kit/notification/notification.css';
import './chanx-kit/presence/presence.css';
import './chanx-kit/chat/chat.css';
import './styles.css';

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
