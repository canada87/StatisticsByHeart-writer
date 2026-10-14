import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ApiError } from './api/client'
import { makeRouter } from './router'
import './styles/index.css'

const queryClient: QueryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error) => {
      // An expired/revoked session anywhere sends the user back to the login page.
      if (error instanceof ApiError && error.status === 401 && !location.pathname.startsWith('/login')) {
        queryClient.removeQueries({ queryKey: ['me'] })
        void router.navigate({ to: '/login', search: { redirect: location.pathname + location.search } as never })
      }
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: true,
      retry: (count, error) => !(error instanceof ApiError && error.status < 500 && error.status !== 0) && count < 2,
    },
  },
})
const router = makeRouter(queryClient)

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
