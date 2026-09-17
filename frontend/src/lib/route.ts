/**
 * The address of a screen.
 *
 * **Hashes, not paths.** The API serves this SPA at `/` and its own routes under `/api`;
 * a path route such as `/piece/12` would 404 on a hard refresh unless the server grew a
 * catch-all, and the whole point of this is a link that opens on the other machine —
 * `http://piano.local:8000/#/repertoire/piece/12` needs no server change at all.
 *
 * Parsing is **total**: anything unrecognised returns null so the caller can leave the
 * app where it is rather than guess. An entity that does not belong to its section is
 * refused for the same reason — `#/log/piece/12` is a typo, not a request.
 *
 * A take has no route of its own: resolving a media id to the piece it belongs to would
 * need a server lookup, and this slice adds no server surface. A take is reached through
 * the piece link that lists it.
 */
import type { AppView } from './types';

export type EntityKind = 'piece' | 'sitting' | 'attempt';

export interface RouteEntity {
  kind: EntityKind;
  id: number;
}

export interface Route {
  name: AppView;
  entity?: RouteEntity;
}

/** Which entities each section may own. A section that owns none has an empty list. */
const ENTITIES: Record<AppView, EntityKind[]> = {
  practice: [],
  calibrate: [],
  stats: ['attempt'],
  log: ['sitting'],
  repertoire: ['piece'],
};

export function routeHash(route: Route): string {
  const base = `#/${route.name}`;
  return route.entity ? `${base}/${route.entity.kind}/${route.entity.id}` : base;
}

export function parseRoute(hash: string): Route | null {
  if (!hash.startsWith('#/')) return null;
  const parts = hash.slice(2).split('/').filter((part) => part.length > 0);
  if (parts.length === 0) return null;

  const name = parts[0] as AppView;
  if (!(name in ENTITIES)) return null;
  if (parts.length === 1) return { name };

  if (parts.length !== 3) return null;
  const kind = parts[1] as EntityKind;
  if (!ENTITIES[name].includes(kind)) return null;
  const id = Number(parts[2]);
  if (!Number.isInteger(id) || id <= 0) return null;
  return { name, entity: { kind, id } };
}
