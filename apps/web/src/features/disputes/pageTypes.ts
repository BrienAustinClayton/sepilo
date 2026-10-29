export interface DisputeDetailPageProps {
  disputeId: string;
}

export interface ServerDisputeDetailParams {
  id: string;
}

export interface ServerDisputeDetailPageProps {
  params: Promise<ServerDisputeDetailParams>;
}
