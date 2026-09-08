export interface FixtureResponse { status: number; body: string; contentType: string }
export function fixtureResponse(href: string, data?: Record<string, unknown>): FixtureResponse
export const fixtures: Record<string, unknown>
