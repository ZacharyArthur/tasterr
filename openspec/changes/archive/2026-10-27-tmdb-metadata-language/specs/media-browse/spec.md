## ADDED Requirements

### Requirement: TMDB text declares its language

TMDB-sourced titles, overviews, and taglines in media cards, the Home hero, and
title detail SHALL carry a `lang` attribute equal to the household metadata
language from `PublicConfig`. Text Tasterr writes itself (labels, buttons, rail
names it generates) SHALL keep the document language. When the config is not yet
loaded, no `lang` attribute SHALL be set rather than a guessed one.

#### Scenario: Spanish title is marked
- **WHEN** the metadata language is `es-ES` and a media card renders
- **THEN** its title element has `lang="es-ES"` and its surrounding controls do not

#### Scenario: Default language
- **WHEN** the metadata language is `en-US`
- **THEN** TMDB text carries `lang="en-US"`
