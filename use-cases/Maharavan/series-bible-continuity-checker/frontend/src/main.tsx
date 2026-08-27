import React from 'react';import ReactDOM from 'react-dom/client';import {GoogleOAuthProvider} from '@react-oauth/google';import {BrowserRouter} from 'react-router-dom';import App from './App';import './styles.css';
const clientId=import.meta.env.VITE_GOOGLE_CLIENT_ID;
const app=<React.StrictMode><BrowserRouter><App/></BrowserRouter></React.StrictMode>;
ReactDOM.createRoot(document.getElementById('root')!).render(clientId?<GoogleOAuthProvider clientId={clientId}>{app}</GoogleOAuthProvider>:app);
