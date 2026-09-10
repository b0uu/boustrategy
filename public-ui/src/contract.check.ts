// Ties the UI's declared types to the payloads the API actually publishes.
//
// The browser tests read a generated fixture, so they pass happily when the API
// and these types drift together out of step with each other: the types can keep
// requiring a field the API stopped sending, and nothing notices until a live
// panel renders undefined. Assigning a real payload to each declared type turns
// that into a compile error. `tsc` runs in type-check and in build, so this is
// checked on every change.
//
// Only presence is asserted here, not value types: a JSON import widens every
// string to `string`, which cannot satisfy unions like Scope. The Python side
// (tests/public/test_contract.py) compares full shapes including types, so the
// two checks together cover both directions.
import sample from '../fixtures/contract-sample.json'
import type {
  ActivityItem,
  ActivityPage,
  Decision,
  FeedPage,
  Overview,
  Performance,
  PolicyCatalog,
  Positions,
  Runtime,
} from './types'

type RequiredKeys<T> = { [K in keyof T]-?: undefined extends T[K] ? never : K }[keyof T]

/** Fails to compile when the payload lacks a field the UI declares as required. */
function declares<T>(payload: Record<RequiredKeys<T> & string, unknown>): void {
  void payload
}

declares<Overview>(sample['live/overview'])
declares<Overview>(sample['paper/overview'])
declares<Positions>(sample['live/positions'])
declares<Positions>(sample['paper/positions'])
declares<Performance>(sample['live/performance'])
declares<Performance>(sample['paper/performance'])
declares<PolicyCatalog>(sample['live/policy'])
declares<PolicyCatalog>(sample['paper/policy'])
declares<Runtime>(sample['live/runtime'])
declares<Runtime>(sample['paper/runtime'])
declares<ActivityPage>(sample['live/activity'])
declares<ActivityPage>(sample['paper/activity'])
declares<FeedPage>(sample['live/feed'])
declares<FeedPage>(sample['paper/feed'])
declares<Decision>(sample['decision/detail'])
declares<ActivityItem>(sample['activity/detail'])

export const publicContractChecked = true
