# GH-53 : mineurs de la validation

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/53. Design court, approuvé par Pierre.

## Pourquoi
Trois défauts relevés aux relectures de la validation (#15), restés en mineurs. Ils sont corrigés avant la 0.9.0.

## Décisions
1. **`integer` et `numeric` : chiffres ASCII seulement.**
   - `integer` : `-?[0-9]+`.
   - `numeric` : `-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?`, sans espaces ni `_`.

   Les deux règles utilisent `re.fullmatch` sur les chaînes. Les nombres JSON (`int`, `float` finis, hors booléens) ne changent pas.
   - Ça casse : `" 12 "` est refusé (Laravel le tolère). C'est noté dans la section « Modifié » du CHANGELOG.
2. **`regex` compilée à la construction du `Validator`** (`_check_params`). Un motif invalide lève `ValueError` en nommant la règle et le champ.
3. **Une `FormRequest` avec valeur par défaut est refusée au `flush` du `Router`.** Un paramètre du handler (méthode de controller ou fonction) annoté par une sous-classe de `FormRequest` et qui a une valeur par défaut lève `RouteError`, avec la route, le paramètre et la raison. Le conteneur ne change pas.

## Approches écartées
- Faire passer une `FormRequest` avant la valeur par défaut dans le conteneur : cela coupler le conteneur à la validation.

## Doc
- `validation.md` : chiffres ASCII pour `integer`/`numeric`, `regex` vérifiée à la construction, pas de valeur par défaut pour une FormRequest.
- `CHANGELOG.md` : sections « Modifié » et « Corrigé ».
