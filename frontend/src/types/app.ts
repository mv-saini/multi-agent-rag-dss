export interface Message {
  id?: string | null;
  role: string;
  content: string;
  reasoning: string;
  isReasoningExpanded: boolean;
  interaction?: PendingInteraction;
  additional_kwargs?: {
    feedback?: {
      id?: string | null;
      question: string;
      answer: string;
    }[];
    plan?: DisplayPlan | null;
    retrieved_context?: {
      [key: string]: string;
    };
  }
}

interface DisplayTool {
  id: string;
  label: string;
  description?: string;
}

interface DisplayDocumentSearch {
  title: string;
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
    message: null;
    display_plan: DisplayPlan;
  }
  | {
    kind: 'clarification';
    message: string;
    display_plan: null;
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
  }
  | {
    action: 'retry';
  };

export type InboundCommand =
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
    type: 'map_layers';
    layers: HazardMapLayer[];
  };

export interface ChatThread {
  id: string;
  title: string;
  date: number;
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