from pydantic import BaseModel, Field

class Profile(BaseModel):
    identity: str
    name: str
    
class Proposal(BaseModel):
    properties: dict = Field(default_factory=dict)
    constraints: str = Field(default="")
    state: str = Field(default="")
    reason: str = Field(default="")
    proposal_id: str = Field(default="", alias="proposalId")

class Demand(BaseModel):
    properties: dict = Field(default_factory=dict)
    constraints: str = Field(default="")

class ProposalEvent(BaseModel):
    event_type: str = Field(default="", alias="eventType")
    event_date: str = Field(default="", alias="eventDate")
    proposal: Proposal = Field(default=Proposal())