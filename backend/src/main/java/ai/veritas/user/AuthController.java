package ai.veritas.user;

import java.security.SecureRandom;
import java.util.HexFormat;

import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import ai.veritas.common.ApiException;
import ai.veritas.security.AuthUser;
import ai.veritas.security.JwtService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private static final SecureRandom RANDOM = new SecureRandom();
    // A real hash of a random value, so a failed lookup costs the same time as a failed password check.
    private final String dummyHash;

    private final UserRepository users;
    private final PasswordEncoder encoder;
    private final JwtService jwt;

    public AuthController(UserRepository users, PasswordEncoder encoder, JwtService jwt) {
        this.users = users;
        this.encoder = encoder;
        this.jwt = jwt;
        this.dummyHash = encoder.encode(randomHex(16));
    }

    public record RegisterRequest(
            @NotBlank(message = "Enter your name.") @Size(max = 120) String name,
            @NotBlank(message = "Enter your email.") @Email(message = "Enter a valid email.") @Size(max = 254) String email,
            @NotBlank @Size(min = 10, max = 128, message = "Use at least 10 characters for the password.") String password) {
    }

    public record LoginRequest(@NotBlank(message = "Enter your email.") String email,
            @NotBlank(message = "Enter your password.") String password) {
    }

    public record UserView(Long id, String email, String name, boolean guest) {
        static UserView of(User u) {
            return new UserView(u.getId(), u.getEmail(), u.getDisplayName(), u.isGuest());
        }
    }

    public record AuthResponse(String token, long expiresIn, UserView user) {
    }

    @PostMapping("/register")
    @ResponseStatus(HttpStatus.CREATED)
    @Transactional
    public AuthResponse register(@Valid @RequestBody RegisterRequest req) {
        String email = req.email().trim().toLowerCase();
        if (users.existsByEmailIgnoreCase(email)) {
            throw ApiException.conflict("EMAIL_TAKEN", "An account with this email already exists. Sign in instead.");
        }
        User u = users.save(new User(email, encoder.encode(req.password()), req.name().trim(), false));
        return new AuthResponse(jwt.issue(u), jwt.ttlSeconds(), UserView.of(u));
    }

    @PostMapping("/login")
    public AuthResponse login(@Valid @RequestBody LoginRequest req) {
        var user = users.findByEmailIgnoreCase(req.email().trim());
        String hash = user.map(User::getPasswordHash).orElse(dummyHash);
        boolean ok = encoder.matches(req.password(), hash);
        if (user.isEmpty() || !ok || user.get().isGuest()) {
            throw ApiException.unauthorized("Email or password is incorrect.");
        }
        return new AuthResponse(jwt.issue(user.get()), jwt.ttlSeconds(), UserView.of(user.get()));
    }

    /** A private, throwaway workspace: lets judges try VERITAS without creating an account. */
    @PostMapping("/guest")
    @ResponseStatus(HttpStatus.CREATED)
    @Transactional
    public AuthResponse guest() {
        String id = randomHex(6);
        User u = users.save(new User("guest-" + id + "@guest.veritas.local", encoder.encode(randomHex(24)),
                "Guest investigator", true));
        return new AuthResponse(jwt.issue(u), jwt.ttlSeconds(), UserView.of(u));
    }

    @GetMapping("/me")
    public UserView me() {
        AuthUser au = AuthUser.current();
        return users.findById(au.id()).map(UserView::of)
                .orElseThrow(() -> ApiException.unauthorized("Your session has ended. Please sign in again."));
    }

    private static String randomHex(int bytes) {
        byte[] b = new byte[bytes];
        RANDOM.nextBytes(b);
        return HexFormat.of().formatHex(b);
    }
}
