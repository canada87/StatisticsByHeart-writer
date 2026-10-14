import type { QueryClient } from '@tanstack/react-query'
import {
  Outlet,
  createRootRouteWithContext,
  createRoute,
  type RouterHistory,
  createRouter,
  redirect,
} from '@tanstack/react-router'
import { meQuery } from './api/queries'
import { AppShell } from './components/AppShell'
import { parseRangeSearch } from './lib/range'
import { LoginPage } from './pages/Login'
import { OverviewPage } from './pages/Overview'
import { SyncDataPage } from './pages/SyncData'

export interface RouterContext {
  queryClient: QueryClient
}

// Root search schema: the global interval (?r=7d | ?r=custom&from&to) is valid on every page.
const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: Outlet,
  validateSearch: (search: Record<string, unknown>) => ({
    ...parseRangeSearch(search),
    tab: typeof search.tab === 'string' ? search.tab : undefined,
    redirect: typeof search.redirect === 'string' ? search.redirect : undefined,
  }),
})

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  component: LoginPage,
})

// Everything inside the shell requires a valid session cookie.
const shellRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'shell',
  component: () => <AppShell />,
  beforeLoad: async ({ context, location }) => {
    try {
      await context.queryClient.ensureQueryData(meQuery())
    } catch {
      throw redirect({ to: '/login', search: { redirect: location.href } as never })
    }
  },
})

const overviewRoute = createRoute({ getParentRoute: () => shellRoute, path: '/', component: OverviewPage })
const syncRoute = createRoute({ getParentRoute: () => shellRoute, path: '/sync', component: SyncDataPage })

const routeTree = rootRoute.addChildren([loginRoute, shellRoute.addChildren([overviewRoute, syncRoute])])

export function makeRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({
    routeTree,
    history,
    context: { queryClient },
    defaultPreload: 'intent',
    scrollRestoration: true,
  })
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof makeRouter>
  }
}
