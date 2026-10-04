package ai.veritas.security;

import org.springframework.security.core.context.SecurityContextHolder;

import ai.veritas.common.ApiException;

/** The authenticated principal, rebuilt from the access token on every request. */
public record AuthUser(Long id, String email, String name, boolean guest) {

    public static AuthUser current() {
        var auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.getPrincipal() instanceof AuthUser u) {
            return u;
        }
        throw ApiException.unauthorized("Please sign in to continue.");
    }
}
