import { useLocation } from 'wouter';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { OverviewTab } from '@/pages/insights/OverviewTab';
import { CostContextTab } from '@/pages/insights/CostContextTab';
import { ActivityTab } from '@/pages/insights/ActivityTab';

type InsightsTab = 'overview' | 'cost-context' | 'activity';

export default function InsightsPage({ tab }: { tab: InsightsTab }) {
  const [, navigate] = useLocation();

  return (
    <div className="mx-auto max-w-[1400px] space-y-6 p-4 md:p-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Insights</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          How your editing sessions are going — from a quick summary to full
          cost and activity detail.
        </p>
      </header>

      <Tabs
        value={tab}
        onValueChange={(value) =>
          navigate(value === 'overview' ? '/insights' : `/insights/${value}`)
        }
      >
        <TabsList>
          <TabsTrigger value="overview" data-testid="tab-insights-overview">
            Overview
          </TabsTrigger>
          <TabsTrigger value="cost-context" data-testid="tab-insights-cost-context">
            Cost &amp; Context
          </TabsTrigger>
          <TabsTrigger value="activity" data-testid="tab-insights-activity">
            Activity Log
          </TabsTrigger>
        </TabsList>
      </Tabs>

      {tab === 'overview' && <OverviewTab />}
      {tab === 'cost-context' && <CostContextTab />}
      {tab === 'activity' && <ActivityTab />}
    </div>
  );
}
