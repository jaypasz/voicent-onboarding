import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router'
import AdminLayout from './admin/AdminLayout'
import ClientDetail from './admin/ClientDetail'
import ClientsPage from './admin/ClientsPage'
import NewOnboardingPage from './admin/NewOnboardingPage'
import OnboardingDetail from './admin/OnboardingDetail'
import OnboardingFollowUpPage from './admin/OnboardingFollowUpPage'
import OnboardingLayout from './admin/OnboardingLayout'
import OnboardingPreviewPage from './admin/OnboardingPreviewPage'
import OnboardingStepsPage from './admin/OnboardingStepsPage'
import OnboardingsPage from './admin/OnboardingsPage'
import SettingsPage from './admin/SettingsPage'
import TemplateBuilderPage from './admin/TemplateBuilderPage'
import TemplatesPage from './admin/TemplatesPage'
import { AuthProvider, useAuth } from './auth/AuthContext'
import Login from './auth/Login'
import PortalPage from './portal/PortalPage'

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } })

function AdminGate() {
  const { ready, signedIn } = useAuth()
  if (!ready) return <main className="narrow"><p>Loading…</p></main>
  return signedIn ? <AdminLayout /> : <Login />
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/c/:token" element={<PortalPage />} />
          <Route element={<AuthProvider><AdminGate /></AuthProvider>}>
            <Route index element={<OnboardingsPage />} />
            <Route path="onboardings/:id" element={<OnboardingLayout />}>
              <Route index element={<OnboardingDetail />} />
              <Route path="steps" element={<OnboardingStepsPage />} />
              <Route path="preview" element={<OnboardingPreviewPage />} />
              <Route path="follow-up" element={<OnboardingFollowUpPage />} />
            </Route>
            <Route path="clients" element={<ClientsPage />} />
            <Route path="clients/:id" element={<ClientDetail />} />
            <Route path="templates" element={<TemplatesPage />} />
            <Route path="templates/new" element={<TemplateBuilderPage key="new" />} />
            <Route path="templates/:id/edit" element={<TemplateBuilderPage key="edit" />} />
            <Route path="new" element={<NewOnboardingPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="*" element={<main className="narrow"><h1>Not found</h1></main>} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
