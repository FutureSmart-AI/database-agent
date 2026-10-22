/**
 * Usage API Types
 *
 * Types for the Usage Events, Owner Configuration, Credentials, and Usage Limits API endpoints
 * Based on OpenAPI spec v0.1.0
 */

// ============================================================================
// Common Types
// ============================================================================

/**
 * Allowed service types for usage events
 */
export type ServiceType =
  | "nl2sql"
  | "knowledge"
  | "actions"
  | "integrations"
  | "dashboard"
  | "orchestrator";

/**
 * Key filter type for analytics queries
 * - "owner-key": Show usage from user-provided API keys (BYOK)
 * - "platform-key": Show usage from platform-provided model keys
 * - (omitted): Show all usage regardless of key type (default)
 */
export type KeyFilterType = "owner-key" | "platform-key";

/**
 * Time bucket for analytics queries
 */
export type TimeBucket = "hour" | "day" | "week" | "month";

/**
 * A single metric measurement
 */
export interface UsageMetric {
  name: string;
  value: number;
}

/**
 * Metric data in event response
 */
export interface EventMetricResponse {
  name: string;
  value: number;
}

// ============================================================================
// Usage Events Types
// ============================================================================

/**
 * Single usage event request
 */
export interface UsageEventRequest {
  service_type: ServiceType;
  operation: string;
  timestamp: string;
  owner_id?: string | null;
  agent_id?: string | null;
  service_id?: string | null;
  label?: string | null;
  session_id?: string | null;
  request_id?: string | null;
  operation_id?: string | null;
  metadata?: Record<string, any> | null;
  metrics?: UsageMetric[] | null;
  key_type?: KeyFilterType | null;
}

/**
 * Bulk usage event recording request
 */
export interface UsageEventsRequest {
  events: UsageEventRequest[];
}

/**
 * Details of a failed event
 */
export interface FailedEvent {
  index: number;
  error: string;
  event: Record<string, any>;
}

/**
 * Response from bulk event recording
 */
export interface UsageEventsResponse {
  processed_count: number;
  failed_count: number;
  failed_events?: FailedEvent[];
}

/**
 * Single usage event in retrieval response
 */
export interface UsageEventResponse {
  event_id: string;
  owner_id?: string | null;
  key_type?: string | null;
  agent_id?: string | null;
  service_id?: string | null;
  service_type: ServiceType;
  operation: string;
  timestamp: string;
  label?: string | null;
  session_id?: string | null;
  request_id?: string | null;
  operation_id?: string | null;
  metadata?: Record<string, any> | null;
  metrics: EventMetricResponse[];
  created_at: string;
}

/**
 * Paginated list of usage events
 */
export interface UsageEventsListResponse {
  total_count: number;
  events: UsageEventResponse[];
  limit: number;
  offset: number;
}

// ============================================================================
// Aggregated Usage Types
// ============================================================================

/**
 * Aggregated metric data
 */
export interface AggregatedMetric {
  metric_name: string;
  total: number;
  avg: number;
  min: number;
  max: number;
  count: number;
}

/**
 * Summary for a specific service and operation
 */
export interface ServiceOperationSummary {
  service_type: ServiceType;
  operation: string;
  event_count: number;
  metrics: AggregatedMetric[];
}

/**
 * Usage summary for an owner
 */
export interface UsageSummaryResponse {
  owner_id: string;
  start_date: string;
  end_date: string;
  total_events: number;
  services: ServiceOperationSummary[];
}

/**
 * Aggregated usage response
 */
export interface AggregatedUsageResponse {
  group_by: string[];
  groups: Array<{
    service_type?: string;
    operation?: string;
    service_id?: string;
    owner_id?: string;
    agent_id?: string;
    label?: string;
    model?: string;
    provider?: string;
    time_bucket?: string;
    event_count: number;
    metrics: AggregatedMetric[];
  }>;
  totals?: {
    request_count?: number;
    total_tokens?: number;
    input_tokens?: number;
    output_tokens?: number;
    total_duration_ms?: number;
    avg_duration_ms?: number | null;
  };
}

// ============================================================================
// Analytics Query Types
// ============================================================================

/**
 * Date range filter for analytics queries
 */
export interface DateRange {
  start: string;
  end: string;
}

/**
 * Filters for analytics queries
 */
export interface AnalyticsFilters {
  agent_ids?: string[];
  service_ids?: string[];
  service_types?: string[];
  operations?: string[];
  labels?: string[];
  key_type?: KeyFilterType | null;
  metadata?: Record<string, string | string[]>;
}

/**
 * Cost breakdown returned by the analytics API
 */
export interface CostBreakdown {
  total_cost_usd: number;
  llm_cost_usd: number;
  llm_input_tokens_cost_usd: number;
  llm_output_tokens_cost_usd: number;
  embedding_cost_usd: number;
  document_processing_cost_usd: number;
  transcription_cost_usd: number;
}

/**
 * Aggregated metrics for analytics (totals object)
 */
export interface AggregatedMetrics {
  request_count: number;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  audio_seconds?: number;
  llama_parse_page_count?: number;
  processed_weblink_count?: number;
  avg_duration_ms?: number;
  total_duration_ms?: number;
  metadata?: Record<string, any>;
  cost?: CostBreakdown;
}

/**
 * Knowledge overview metrics (only present when group_by is empty)
 */
export interface KnowledgeOverviewMetrics {
  total_files_processed: number;
  total_char_count: number;
  total_audio_seconds: number;
  total_llama_parse_pages: number;
  total_weblink_pages: number;
  total_text_count: number;
  total_embedding_tokens: number;
  total_vectors_indexed: number;
  cost?: CostBreakdown;
}

/**
 * A single data point in analytics response
 */
export interface AnalyticsDataPoint {
  dimensions: Record<string, string>;
  metrics: AggregatedMetrics;
}

/**
 * Analytics query request (single mode)
 */
export interface AnalyticsQueryRequest {
  owner_id: string;
  date_range: DateRange;
  filters?: AnalyticsFilters | null;
  group_by?: string[] | null;
  time_bucket?: TimeBucket | null;
  metrics_to_include?: string[] | null;
  /**
   * Whose key paid is `filters.key_type`, not a field out here. The route
   * ignores an unknown top-level key and answers 200 over the whole window, so
   * a `key_filter` sibling read as a working control that narrowed nothing.
   */
  limit?: number | null;
  offset?: number | null;
}

/**
 * Batch query item
 */
export interface BatchQueryItem {
  query_id: string;
  date_range: DateRange;
  filters?: AnalyticsFilters;
  group_by?: string[];
  time_bucket?: TimeBucket;
  metrics_to_include?: string[];
  limit?: number;
  offset?: number;
}

/**
 * Batch query request - multiple queries in a single API call
 */
export interface BatchQueryRequest {
  owner_id: string;
  queries: BatchQueryItem[];
}

/**
 * Analytics query response (individual query result within batch)
 */
export interface AnalyticsQueryResponse {
  date_range: DateRange;
  group_by: string[];
  time_bucket?: string | null;
  totals: AggregatedMetrics;
  knowledge_overview_metrics?: KnowledgeOverviewMetrics | null;
  data: AnalyticsDataPoint[];
  total_groups: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

/**
 * Error details for a failed query in a batch
 */
export interface QueryError {
  code: string;
  message: string;
}

/**
 * Result item within batch response
 */
export interface BatchQueryResultItem {
  query_id: string;
  success: boolean;
  data: AnalyticsQueryResponse | null;
  error: QueryError | string | null;
}

/**
 * Batch query response
 */
export interface BatchQueryResponse {
  owner_id: string;
  executed_at: string;
  results: BatchQueryResultItem[];
  total_queries: number;
  successful_queries: number;
  failed_queries: number;
}

// ============================================================================
// Service Options Types
// ============================================================================

/**
 * A single label option within an operation
 */
export interface LabelOption {
  label: string;
  display_name: string;
}

/**
 * A single operation option
 */
export interface OperationOption {
  operation: string;
  display_name: string;
  labels?: LabelOption[];
}

/**
 * Service type option
 */
export interface ServiceTypeOption {
  service_type: string;
  display_name: string;
  description?: string | null;
  operations?: OperationOption[];
}

/**
 * Response containing service types, operations, and labels
 */
export interface ServiceOptionsResponse {
  service_types: ServiceTypeOption[];
  all_operations?: string[];
  all_labels?: string[];
}

/**
 * Filter value option
 */
export interface UsageFilterValue {
  value: string;
  label: string;
}

export interface UsageFilterValuesResponse {
  items: UsageFilterValue[];
}

// ============================================================================
// Owner Configuration Types
// ============================================================================

/**
 * Default models for an owner
 */
export interface DefaultModels {
  llm: string;
  embedding: string;
  enrichment_llm: string;
}

/**
 * Partial update for default models (all optional)
 */
export interface DefaultModelsPartial {
  llm?: string | null;
  embedding?: string | null;
  enrichment_llm?: string | null;
}

/**
 * Platform limits for an owner
 */
export interface PlatformLimits {
  max_agents?: number | null;
  max_team_members?: number | null;
  max_file_size_mb?: number | null;
  max_indexed_characters?: number | null;
  max_conversations_per_month?: number | null;
  max_messages_per_month?: number | null;
  max_llm_tokens_per_month?: number | null;
}

/**
 * Service enablement info with features
 */
export interface ServiceFeatures {
  enabled: boolean;
  enabled_at?: string | null;
  features: Record<string, boolean>;
}

/**
 * Owner configuration response
 */
export interface OwnerConfigResponse {
  owner_id: string;
  tier_name: string;
  platform_limits: PlatformLimits;
  default_models: DefaultModels;
  services: Record<string, ServiceFeatures>;
  created_at: string;
  updated_at: string;
}

/**
 * Request to register an owner
 */
export interface OwnerRegisterRequest {
  owner_id: string;
  tier_name?: string;
}

/**
 * Response from owner registration
 */
export interface OwnerRegisterResponse {
  owner_id: string;
  tier_name: string;
  created: boolean;
}

/**
 * Request to create/replace owner configuration
 */
export interface OwnerConfigCreateRequest {
  tier_name?: string;
  platform_limits?: PlatformLimits;
  default_models?: DefaultModels;
  services?: Record<string, ServiceFeatures>;
}

/**
 * Request to patch owner configuration
 */
export interface OwnerConfigPatchRequest {
  tier_name?: string;
  platform_limits?: PlatformLimits;
  default_models?: DefaultModelsPartial;
}

/**
 * Request to enable a service
 */
export interface ServiceEnableRequest {
  service_name: string;
  features?: Record<string, boolean> | null;
}

/**
 * Request to disable a service
 */
export interface ServiceDisableRequest {
  service_name: string;
}

/**
 * Response for single service operation
 */
export interface ServiceResponse {
  owner_id: string;
  service_name: string;
  enabled: boolean;
  enabled_at?: string | null;
  features: Record<string, boolean>;
}

/**
 * Response for listing services
 */
export interface ServicesListResponse {
  owner_id: string;
  services: Record<string, ServiceFeatures>;
}

/**
 * Metadata about a valid service
 */
export interface ServiceMetadata {
  name: string;
  description: string;
  default_enabled: boolean;
}

/**
 * Response listing all valid services
 */
export interface ValidServicesResponse {
  services: ServiceMetadata[];
}

/**
 * Response listing providers
 */
export interface ProviderListResponse {
  llm_providers: string[];
  /**
   * Optional: it held `llamaparse` and `firecrawl`, and a service with no
   * document-parsing or web-scraping path (NL2SQL) omits the field entirely.
   */
  document_and_web_providers?: string[];
}

// ============================================================================
// Credentials Types
// ============================================================================

/**
 * Request to add/update credential
 */
export interface CredentialAddRequest {
  provider: string;
  api_key: string;
}

/**
 * Credential data in response (without actual key)
 */
export interface CredentialData {
  provider: string;
  mask: string;
  is_valid: boolean;
  updated_at: string;
}

/**
 * Response for adding/updating credential
 */
export interface CredentialAddResponse {
  status: "success";
  /** Absent on the NL2SQL service, which answers with `status` and `data` only. */
  message?: string;
  data: CredentialData;
}

/**
 * Response for listing credentials
 */
export interface CredentialListResponse {
  data: CredentialData[];
}

/**
 * Response for deleting credential
 */
export interface CredentialDeleteResponse {
  status: "success";
  message: string;
}

/**
 * Error response for credential operations
 */
export interface CredentialErrorResponse {
  status: "error";
  code: string;
  message: string;
}

// ============================================================================
// Usage Limits Management Types
// ============================================================================

/**
 * Usage limit add payload
 */
export interface UsageLimitAdd {
  feature: string;
  limit_key: string;
  daily_limit?: number | null;
  total_limit: number;
  cost_limit_usd?: number | null;
}

/**
 * Model access add payload
 */
export interface ModelAccessAdd {
  feature: string;
  provider?: string | null;
  allowed_models?: string[] | null;
  default_model?: string | null;
  enabled?: boolean | null;
}

/**
 * Feature flag add payload
 */
export interface FeatureFlagAdd {
  feature: string;
  feature_values: string[];
  default_value: string;
}

/**
 * Tier limits add payload
 */
export interface TierLimitsAddPayload {
  tier_name: string;
  usage?: UsageLimitAdd[] | null;
  models?: ModelAccessAdd[] | null;
  feature_flags?: FeatureFlagAdd[] | null;
}

/**
 * User update usage limit
 */
export interface UserUpdateUsageLimit {
  feature: string;
  limit_key: string;
  daily_limit?: number | null;
  total_limit?: number | null;
  cost_limit_usd?: number | null;
  custom_override?: boolean | null;
}

/**
 * User update model access
 */
export interface UserUpdateModelAccess {
  feature: string;
  provider?: string | null;
  allowed_models?: string[] | null;
  default_model?: string | null;
  enabled?: boolean | null;
  custom_override?: boolean | null;
}

/**
 * User update feature flag
 */
export interface UserUpdateFeatureFlag {
  feature: string;
  feature_values?: string[] | null;
  default_value?: string | null;
  custom_override?: boolean | null;
}

/**
 * User limits update section
 */
export interface UserLimitsUpdate {
  usage?: UserUpdateUsageLimit[] | null;
  models?: UserUpdateModelAccess[] | null;
  feature_flags?: UserUpdateFeatureFlag[] | null;
}

/**
 * Tier limits update payload
 */
export interface TierLimitsUpdatePayload {
  tier_name: string;
  usage?: UsageLimitAdd[] | null;
  models?: ModelAccessAdd[] | null;
  feature_flags?: FeatureFlagAdd[] | null;
}

/**
 * User limits update payload
 */
export interface UserLimitsUpdatePayload {
  limits: UserLimitsUpdate;
}

/**
 * Usage update payload
 */
export interface UsageUpdatePayload {
  usage_type: "file" | "text" | "url" | "conversation" | "custom_action";
  char_count?: number | null;
  chatbot_id?: string | null;
  agentic_rag?: boolean | null;
  content_type?: string | null;
  llama_parse_page_count?: number | null;
  url_count?: number | null;
  page_count?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
}

/**
 * Period info
 */
export interface PeriodInfo {
  start: string;
  end: string;
}

/**
 * Limits info
 */
export interface LimitsInfo {
  max_agents?: number | null;
  max_indexed_characters?: number | null;
  max_conversations_per_month?: number | null;
  max_messages_per_month?: number | null;
  max_llm_tokens_per_month?: number | null;
}

/**
 * Current usage info
 */
export interface CurrentUsageInfo {
  agents_count: number;
  indexed_characters: number;
  conversations_this_month: number;
  messages_this_month: number;
  llm_tokens_this_month: number;
}

/**
 * Remaining quota info
 */
export interface RemainingQuotaInfo {
  agents?: number | null;
  indexed_characters?: number | null;
  conversations?: number | null;
  messages?: number | null;
  llm_tokens?: number | null;
}

/**
 * Usage status response
 */
export interface UsageStatusResponse {
  owner_id: string;
  period: PeriodInfo;
  limits: LimitsInfo;
  current_usage: CurrentUsageInfo;
  remaining: RemainingQuotaInfo;
}
