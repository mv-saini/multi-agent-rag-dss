export interface Message {
  id?: string | null;
  role: string;
  content: string;
  reasoning: string;
  isReasoningExpanded: boolean;
  interaction?: PendingInteraction;
  additional_kwargs?: {
    evidence_bundle_id?: string | null;
    feedback?: {
      id?: string | null;
      question: string;
      answer: string;
    }[];
    plan?: DisplayPlan | null;
  }
}

export interface CitationSource {
  id: string;
  label: string;
  kind: 'document' | 'web' | 'spatial';
  title: string;
  text: string;
  page?: string | number | null;
  url?: string | null;
}

interface DisplayTool {
  id: string;
  label: string;
  description?: string;
}

interface DisplayDocumentSearch {
  title: string;
  target_document_id?: string | null;
  target_file?: string | null;
  queries: string[];
}

interface DisplayHazard {
  id?: string | number | null;
  name: string;
}

interface DisplayLocation {
  type: 'region' | 'province' | 'city' | string;
  name: string;
  id?: string | number | null;
  parent?: string | null;
}

export interface DisplaySpatialAnalysis {
  title: string;
  hazards: DisplayHazard[];
  locations: DisplayLocation[];
  seismic_scenarios?: SeismicScenario[];
}

export interface SeismicScenario {
  fault_id: string;
  magnitude: number;
  resolution_m: number;
  intensity_measure: 'PGA' | 'PGV' | 'SA';
  period_s: number | null;
  area_mode: 'fault_buffer' | 'bbox';
  buffer_km: number | null;
  bbox: [number, number, number, number] | null;
  rake: number | null;
  vs30_override: number | null;
  grid_origin_x: number;
  grid_origin_y: number;
}

export interface ScenarioRequest {
  draft: Partial<SeismicScenario>;
  geographic_context: { region_name: string; province?: { province_name: string; city?: { city_name: string }[] }[] }[];
}

export interface ScenarioSelection {
  scenario: SeismicScenario;
}

interface DisplayWebResult {
  title: string;
  url: string;
  content: string;
  score: number;
  query: string;
  extracted: boolean;
}

export interface DisplayPlan {
  title: string;
  tools: DisplayTool[];
  document_searches: DisplayDocumentSearch[];
  spatial_analyses: DisplaySpatialAnalysis[];
  web_results: DisplayWebResult[];
}

export type PendingInteraction =
  | {
    kind: 'plan_approval';
    message: string | null;
    display_plan: DisplayPlan;
  }
  | {
    kind: 'clarification';
    message: string;
    display_plan: null;
    scenario_request?: ScenarioRequest | null;
  };

export type OutboundCommand =
  | {
    action: 'query';
    query: string;
    user_profile: Record<string, any>;
  }
  | {
    action: 'resume';
    response: string;
    checkpoint_id?: string | null;
    scenario_selection?: ScenarioSelection;
  }
  | {
    action: 'retry';
  };

export type InboundCommand =
  | {
    type: 'new_thread';
    thread: ChatThread;
  }
  | {
    type: 'stream_started';
    command: 'query' | 'resume';
  }
  | {
    type: 'message_started';
    message_id: string;
  }
  | {
    type: 'message_update';
    message: Message;
  }
  | {
    type: 'approval_required';
    interaction: PendingInteraction;
    checkpoint_id?: string | null;
  }
  | {
    type: 'stream_complete';
    status: 'paused' | 'completed';
    checkpoint_id?: string | null;
  }
  | {
    type: 'stream_error';
    code: string;
    message: string;
    checkpoint_id?: string | null;
  }
  | {
    type: 'token' | 'reasoning';
    content: string;
  }
  | {
    type: 'tool_start' | 'tool_end';
    name: string;
    input?: Record<string, any>;
  }
  | {
    type: 'retriever_start';
    query?: string;
  }
  | {
    type: 'custom_event';
    name: string;
    data: any;
  }
  | {
    type: 'evidence_available';
    evidence_bundle_id: string;
  };

export interface ChatThread {
  id: number;
  conversationid: string;
  userid: number;
  title: string;
  datetime: string | null;
}

export interface ContextMenuState {
  open: boolean;
  x: number;
  y: number;
  thread: ChatThread | null;
}

export interface HazardMapLegendItem {
  label: string;
  color: string;
}

interface HazardMapSummaryMetrics {
  geometry_type?: string;
  total_points?: number;
  estimated_grid_resolution_meters?: number | string;
  max_intensity_recorded?: number;
  seismic_acceleration_ag?: {
    min?: number;
    mean?: number;
    max?: number;
  };
}

interface HazardRiskBreakdownItem {
  risk_label: string;
  affected_area_sqkm?: number;
  percent_of_territory?: number;
  point_count?: number;
  exposed_population?: number;
  exposed_residential_houses?: number;
  exposed_residential_buildings?: number;
  exposed_families?: number;
  housing_occupancy_percentage?: number;
  average_people_per_building?: number;
  has_data?: boolean;
}

export interface HazardMapLayer {
  download_url?: string;
  scenario_group?: string;
  geojson_source?: string;
  view_label?: string;
  render_style?: { opacity: number; point_radius: number; outline_width: number; outline_color?: string };
  raster_image?: { url: string; coordinates: [[number, number], [number, number], [number, number], [number, number]] };
  layer_id: string;
  layer_name: string;
  hazard_name?: string;
  location_name?: string;
  geometry_type: string;
  style_property?: string;
  label_property?: string;
  geojson: GeoJSON.FeatureCollection;
  legend: HazardMapLegendItem[];
  summary_metrics?: HazardMapSummaryMetrics;
  risk_breakdown_key?:
  | "intensity_breakdown"
  | "seismic_discrete_zones"
  | "multi_hazard_spatial_breakdown";
  risk_breakdown?: HazardRiskBreakdownItem[];
  feature_count?: number;
  empty?: boolean;
}

export interface ThreadState {
  thread_id: string;
  exists: boolean;
  is_running: boolean;
  checkpoint_id?: string;
  messages: Message[];
  evidence_bundle_ids: string[];
  is_errored: boolean;
  pending_interaction?: PendingInteraction;
}

export interface EvidenceBundle {
  id: string;
  retrieved_context: Record<string, string>;
  citation_sources: Record<string, CitationSource>;
  map_layers: HazardMapLayer[];
  web_results: DisplayWebResult[];
}
