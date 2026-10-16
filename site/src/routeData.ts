import { defineRouteMiddleware } from '@astrojs/starlight/route-data';
import { site } from './site.config';

// Docs head tweaks: brand the social title, and keep the 404 page out of indexes.
export const onRequest = defineRouteMiddleware((context) => {
  const route = context.locals.starlightRoute;
  for (const tag of route.head) {
    const key = tag.attrs?.property ?? tag.attrs?.name;
    if ((key === 'og:title' || key === 'twitter:title') && typeof tag.attrs?.content === 'string') {
      tag.attrs.content = `${tag.attrs.content} | ${site.name}`;
    }
  }
  if (route.id === '404' || context.url.pathname.endsWith('/404/') || context.url.pathname.endsWith('/404')) {
    route.head.push({ tag: 'meta', attrs: { name: 'robots', content: 'noindex' } });
  }
});
