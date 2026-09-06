import module from './fixtures/statistics.json'
import version from './fixtures/statistics-0.4.0.json'
import type { PackageDetail, PackageRelease } from '~/types/api'
export const detail = module as PackageDetail
export const release = version as PackageRelease
export const page = { items: [detail], total: 1, limit: 50, offset: 0 }
export const publisher = {
  id: detail.publisher.id,
  name: detail.publisher.name,
  module_count: 1,
}
