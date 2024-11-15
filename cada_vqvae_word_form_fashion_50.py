# -*- coding: utf-8 -*-
"""cada_vqvae_word_form_fashion_50.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1PjgS0Gb3G1BS-RyFpQtz418GTugXtfWD
"""

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torchvision import datasets, transforms
from torch.utils.data import DataLoader
import gensim.downloader as api

# Load Gensim word embeddings
word_vectors = api.load("glove-wiki-gigaword-100")  # Load GloVe embeddings (100 dimensions)

# Data loading and transformation
transform = transforms.Compose([
    transforms.ToTensor(),
    transforms.Lambda(lambda x: x.view(-1)),
])

from torchvision import datasets, transforms
train_dataset = datasets.FashionMNIST('./data', train=True, download=True, transform=transform)
train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True)

val_dataset = datasets.FashionMNIST('./data', train=False, download=True, transform=transform)
val_loader = DataLoader(val_dataset, batch_size=64, shuffle=False)

fashion_mnist_classes = [
    "shirt", "trouser", "pullover", "dress", "coat",
    "sandal", "shirt", "sneaker", "bag", "boot"
]

# Rest of your code remains the same

# Define a mapping from FashionMNIST classes to word embeddings
# def get_semantic_embedding(labels, word_vectors):
#     return torch.stack([torch.tensor(word_vectors[fashion_mnist_classes[label]]) for label in labels], dim=0)
class_to_index = {cls: idx for idx, cls in enumerate(fashion_mnist_classes)}

# Image Encoder
class ImageEncoder(nn.Module):
    def __init__(self, latent_size):
        super(ImageEncoder, self).__init__()
        self.encoder = nn.Sequential(
            nn.Linear(28*28, 400),  # Input: flattened image (3x32x32)
            nn.ELU(),
            nn.Linear(400, 200),
            nn.ELU(),
        )
        self.fc_mu = nn.Linear(200, latent_size)       # Mean for latent space
        self.fc_logvar = nn.Linear(200, latent_size)   # Log variance for latent space

    def forward(self, x):
        h1 = self.encoder(x)  # Flatten the input
        mu = self.fc_mu(h1)                          # Mean of latent space
        logvar = self.fc_logvar(h1)                  # Log variance of latent space
        return mu, logvar

# Image Decoder
class ImageDecoder(nn.Module):
    def __init__(self, latent_size):
        super(ImageDecoder, self).__init__()
        self.decoder = nn.Sequential(
            nn.Linear(latent_size, 200),   # Input: latent space
            nn.ELU(),
            nn.Linear(200, 400),
            nn.ELU(),
            nn.Linear(400, 28*28),  # Output: flattened 3x32x32 image
            nn.Tanh(),                     # Output range between -1 and 1 due to normalization
        )

    def forward(self, z):
        return self.decoder(z)             # Decode latent vector to reconstruct image

# Vector Quantizer for VQ-VAE
class VectorQuantizer(nn.Module):
    def __init__(self, num_embeddings, embedding_dim, commitment_cost=0.25):
        super(VectorQuantizer, self).__init__()
        self.num_embeddings = num_embeddings
        self.embedding_dim = embedding_dim
        self.commitment_cost = commitment_cost

        # Initialize the codebook (embedding table)
        self.embedding = nn.Embedding(self.num_embeddings, self.embedding_dim)
        self.embedding.weight.data.uniform_(-1/self.num_embeddings, 1/self.num_embeddings)

    def forward(self, inputs):
        flat_inputs = inputs.view(-1, self.embedding_dim)
        distances = torch.sum(flat_inputs**2, dim=1, keepdim=True) + \
                    torch.sum(self.embedding.weight**2, dim=1) - \
                    2 * torch.matmul(flat_inputs, self.embedding.weight.t())
        encoding_indices = torch.argmin(distances, dim=1).unsqueeze(1)
        quantized = self.embedding(encoding_indices).view_as(inputs)

        commitment_loss = self.commitment_cost * F.mse_loss(quantized.detach(), inputs)
        quantization_loss = F.mse_loss(quantized, inputs.detach())
        quantized = inputs + (quantized - inputs).detach()

        return quantized, quantization_loss, commitment_loss

class SemanticEncoderVQVAE(nn.Module):
    def __init__(self, latent_size, num_embeddings, embedding_dim):
        super(SemanticEncoderVQVAE, self).__init__()
        self.encoder = nn.Sequential(
            nn.Linear(100, 200),
            nn.ELU(),
            nn.Linear(200, latent_size),  # Ensure this matches latent_size
        )
        self.vq_layer = VectorQuantizer(num_embeddings, latent_size)

        # Adding mu and logvar layers like in the ImageEncoder
        self.fc_mu = nn.Linear(latent_size, latent_size)
        self.fc_logvar = nn.Linear(latent_size, latent_size)

    def forward(self, c):
        z_e = self.encoder(c)  # Continuous latent encoding
        z_q, quantization_loss, commitment_loss = self.vq_layer(z_e)

        mu_c = self.fc_mu(z_e)
        logvar_c = self.fc_logvar(z_e)

        return mu_c, logvar_c, z_q, z_e, quantization_loss, commitment_loss

# Semantic Decoder
class SemanticDecoder(nn.Module):
    def __init__(self, latent_size):
        super(SemanticDecoder, self).__init__()
        self.decoder = nn.Sequential(
            nn.Linear(latent_size, 200),
            nn.ELU(),
            nn.Linear(200, 100),
            nn.Sigmoid(),
        )

    def forward(self, z):
        return self.decoder(z)

class CADA_VAE(nn.Module):
    def __init__(self, latent_size, num_embeddings, embedding_dim):
        super(CADA_VAE, self).__init__()

        # Image encoder and decoder
        self.image_encoder = ImageEncoder(latent_size)
        self.image_decoder = ImageDecoder(latent_size)

        # Semantic encoder and decoder with VQ-VAE
        self.semantic_encoder = SemanticEncoderVQVAE(latent_size, num_embeddings, embedding_dim)
        self.semantic_decoder = SemanticDecoder(latent_size)

    def reparameterize(self, mu, logvar):
        """Reparameterization trick: sample from latent space using mu and logvar."""
        std = torch.exp(0.5 * logvar)
        eps = torch.randn_like(std)
        return mu + eps * std

    def forward(self, x, c):
        # Image VAE
        mu_x, logvar_x = self.image_encoder(x)
        z_x = self.reparameterize(mu_x, logvar_x)
        recon_x = self.image_decoder(z_x)

        # Semantic VQ-VAE
        mu_c, logvar_c, z_q, z_e, quantization_loss, commitment_loss = self.semantic_encoder(c)

        recon_c = self.semantic_decoder(z_q)

        return recon_x, recon_c, mu_x, logvar_x, mu_c, logvar_c, z_e, quantization_loss, commitment_loss

def vae_loss(recon, target, mu, logvar, beta=1.0):
    # Compute reconstruction loss (MSE) between the input and reconstructed output
    # Reshape tensors to (batch_size, channels*height*width) for pixel-wise comparison
    recon_loss = F.mse_loss(recon.view(-1, 28*28), target.view(-1,28*28), reduction='sum')

    # Compute KL divergence loss between the learned distribution and standard normal distribution
    # Formula: -0.5 * sum(1 + log(sigma^2) - mu^2 - sigma^2)
    kld_loss = -0.5 * torch.sum(1 + logvar - mu.pow(2) - logvar.exp())

    # Return weighted sum of reconstruction and KL divergence losses
    # Beta parameter controls the importance of the KL divergence term
    return recon_loss + beta * kld_loss

def cada_vae_loss(recon_x_from_x, x, recon_c_from_c, c, recon_x_from_c, recon_c_from_x,
                  mu_x, logvar_x, z_e, quantization_loss, commitment_loss, beta, gamma, delta):
    # Standard VAE loss for input reconstruction
    loss_x = vae_loss(recon_x_from_x, x, mu_x, logvar_x, beta)

    # MSE loss for class embedding reconstruction
    loss_c = F.mse_loss(recon_c_from_c, c)

    # Cross-aligned auto-encoder loss
    ca_loss = F.mse_loss(recon_x_from_c, x) + F.mse_loss(recon_c_from_x, c)

    # Distribution-aligned loss
    da_loss = torch.norm(mu_x - z_e) ** 2

    # Vector quantization loss from VQ-VAE
    vq_vae_loss = quantization_loss + commitment_loss

    # Total loss combines all individual losses with respective weights
    total_loss = loss_x + gamma * ca_loss + delta * da_loss + vq_vae_loss + loss_c

    # Return total loss and individual components
    return total_loss, loss_x, loss_c, ca_loss, da_loss, vq_vae_loss , loss_c , loss_x

# Define a mapping from CIFAR-10 classes to words
def get_semantic_embedding(labels, word_vectors):
    return torch.stack([torch.tensor(word_vectors[fashion_mnist_classes[label]]) for label in labels], dim=0)

# Training the model
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
latent_size = 20
num_embeddings = 512  # Example: size of the VQ-VAE codebook
embedding_dim = 100  # Example: dimensionality of the latent embeddings

# Initialize the CADA_VAE model
model = CADA_VAE(latent_size, num_embeddings, embedding_dim).to(device)

# Initialize the optimizer
optimizer = optim.Adam(model.parameters(), lr=0.00001)

# Define coefficients for loss functions
beta = 1.0  # Weight for the reconstruction loss of images
gamma = 2.0 # Weight for the correspondence loss
delta = 1.0 # Weight for the distribution alignment loss
epochs = 50
# # Start the training loop
# for epoch in range(epochs):
#     model.train()
#     for batch_idx, (data, target) in enumerate(train_loader):
#         data, target = data.to(device), target.to(device)

#         # Get semantic embeddings
#         semantic_embeddings = get_semantic_embedding(target.cpu().numpy(), word_vectors).to(device)

#         optimizer.zero_grad()

#         recon_x, recon_c, mu_x, logvar_x, mu_c, logvar_c, z_e, quantization_loss, commitment_loss = model(data, semantic_embeddings)

#         loss = cada_vae_loss(
#             recon_x, data, recon_c, semantic_embeddings, recon_x, recon_c,
#             mu_x, logvar_x, z_e, quantization_loss, commitment_loss, beta, gamma, delta
#         )

#         loss.backward()
#         optimizer.step()

#         if batch_idx % 100 == 0:
#             print(f'Epoch {epoch}, Batch {batch_idx}, Loss: {loss.item()}')
import matplotlib.pyplot as plt

# Initialize dicts to store losses
train_losses = {
    'total_loss': [],
    'vae_loss': [],
    'cada_loss': [],
    'ca_loss': [],
    'da_loss': [],
    'vq_vae_loss': [],
    'loss_c': [],
    'loss_x': []

}

val_losses = {
    'total_loss': [],
    'vae_loss': [],
    'cada_loss': [],
    'ca_loss': [],
    'da_loss': [],
    'vq_vae_loss': [],
    'loss_c': [],
    'loss_x': []
}



for epoch in range(epochs):
    model.train()
    total_train_loss = 0

    for batch_idx, (data, target) in enumerate(train_loader):
        data, target = data.to(device), target.to(device)
        semantic_embeddings = get_semantic_embedding(target.cpu().numpy(), word_vectors).to(device)

        optimizer.zero_grad()

        # Forward pass
        recon_x, recon_c, mu_x, logvar_x, mu_c, logvar_c, z_e, quantization_loss, commitment_loss = model(data, semantic_embeddings)

        # Calculate total loss and individual components using the modified cada_vae_loss function
        total_loss, vae_loss_value, cada_loss_value, ca_loss_value, da_loss_value, vq_vae_loss_value,loss_c_value,loss_x_value = cada_vae_loss(
            recon_x, data, recon_c, semantic_embeddings, recon_x, recon_c,
            mu_x, logvar_x, z_e, quantization_loss, commitment_loss, beta, gamma, delta
        )

        # Backpropagation and optimization
        total_loss.backward()
        optimizer.step()

        # Accumulate total loss for this batch
        total_train_loss += total_loss.item()

    # Average losses over the epoch and store them
    train_losses['total_loss'].append(total_train_loss / len(train_loader))
    train_losses['vae_loss'].append(vae_loss_value.item() / len(train_loader))
    train_losses['cada_loss'].append(cada_loss_value.item() / len(train_loader))
    train_losses['ca_loss'].append(ca_loss_value.item() / len(train_loader))
    train_losses['da_loss'].append(da_loss_value.item() / len(train_loader))
    train_losses['vq_vae_loss'].append(vq_vae_loss_value.item() / len(train_loader))
    train_losses['loss_c'].append(loss_c_value.item() / len(train_loader))
    train_losses['loss_x'].append(loss_x_value.item() / len(train_loader))

    # Validation loop
    model.eval()
    total_val_loss = 0
    with torch.no_grad():
        for val_data, val_target in val_loader:
            val_data, val_target = val_data.to(device), val_target.to(device)
            val_semantic_embeddings = get_semantic_embedding(val_target.cpu().numpy(), word_vectors).to(device)

            # Forward pass
            val_recon_x, val_recon_c, val_mu_x, val_logvar_x, val_mu_c, val_logvar_c, val_z_e, val_quantization_loss, val_commitment_loss = model(val_data, val_semantic_embeddings)

            # Calculate validation total loss and components
            val_total_loss, val_vae_loss_value, val_cada_loss_value, val_ca_loss_value, val_da_loss_value, val_vq_vae_loss_value , val_loss_c_value , val_loss_x_value= cada_vae_loss(
                val_recon_x, val_data, val_recon_c, val_semantic_embeddings, val_recon_x, val_recon_c,
                val_mu_x, val_logvar_x, val_z_e, val_quantization_loss, val_commitment_loss, beta, gamma, delta
            )

            # Accumulate validation total loss for this batch
            total_val_loss += val_total_loss.item()

    # Store validation losses for this epoch
    val_losses['total_loss'].append(total_val_loss / len(val_loader))
    val_losses['vae_loss'].append(val_vae_loss_value.item() / len(val_loader))
    val_losses['cada_loss'].append(val_cada_loss_value.item() / len(val_loader))
    val_losses['ca_loss'].append(val_ca_loss_value.item() / len(val_loader))
    val_losses['da_loss'].append(val_da_loss_value.item() / len(val_loader))
    val_losses['vq_vae_loss'].append(val_vq_vae_loss_value.item() / len(val_loader))
    val_losses['loss_c'].append(val_loss_c_value.item() / len(train_loader))
    val_losses['loss_x'].append(val_loss_x_value.item() / len(train_loader))

    # Print epoch summary
    print(f'Epoch {epoch}, Train Loss: {train_losses["total_loss"][-1]:.4f}, Val Loss: {val_losses["total_loss"][-1]:.4f}')


# Plot the loss curves
plt.figure(figsize=(12, 6))


# Individual loss functions in separate graphs
plt.subplot(2, 3, 2)
plt.plot(train_losses['vae_loss'], label='Train VAE Loss')
plt.plot(val_losses['vae_loss'], label='Val VAE Loss')
plt.title('VAE Loss')
plt.xlabel('Epoch')
plt.ylabel('Loss Value')
plt.legend()

plt.subplot(2, 3, 3)
plt.plot(train_losses['cada_loss'], label='Train CADA Loss')
plt.plot(val_losses['cada_loss'], label='Val CADA Loss')
plt.title('CADA Loss')
plt.xlabel('Epoch')
plt.ylabel('Loss Value')
plt.legend()

plt.subplot(2, 3, 4)
plt.plot(train_losses['ca_loss'], label='Train CA Loss')
plt.plot(val_losses['ca_loss'], label='Val CA Loss')
plt.title('CA Loss')
plt.xlabel('Epoch')
plt.ylabel('Loss Value')
plt.legend()

plt.subplot(2, 3, 5)
plt.plot(train_losses['da_loss'], label='Train DA Loss')
plt.plot(val_losses['da_loss'], label='Val DA Loss')
plt.title('DA Loss')
plt.xlabel('Epoch')
plt.ylabel('Loss Value')
plt.legend()

plt.subplot(2, 3, 6)
plt.plot(train_losses['vq_vae_loss'], label='Train VQ-VAE Loss')
plt.plot(val_losses['vq_vae_loss'], label='Val VQ-VAE Loss')
plt.title('VQ-VAE Loss')
plt.xlabel('Epoch')
plt.ylabel('Loss Value')
plt.legend()

plt.tight_layout()
plt.show()

import matplotlib.pyplot as plt

# Setting a larger figure size for clarity
plt.figure(figsize=(18, 10))

# VAE Loss
plt.subplot(2, 3, 1)
plt.plot(train_losses['vae_loss'], label='Train VAE Loss', color='blue', linewidth=2)
plt.plot(val_losses['vae_loss'], label='Val VAE Loss', color='orange', linewidth=2)
plt.title('VAE Loss Over Epochs', fontsize=16)
plt.xlabel('Epoch', fontsize=14)
plt.ylabel('Loss Value', fontsize=14)
plt.xticks(fontsize=12)
plt.yticks(fontsize=12)
plt.grid(True, linestyle='--', alpha=0.7)
plt.legend(fontsize=12)

# CADA Loss
plt.subplot(2, 3, 2)
plt.plot(train_losses['cada_loss'], label='Train CADA Loss', color='green', linewidth=2)
plt.plot(val_losses['cada_loss'], label='Val CADA Loss', color='red', linewidth=2)
plt.title('CADA Loss Over Epochs', fontsize=16)
plt.xlabel('Epoch', fontsize=14)
plt.ylabel('Loss Value', fontsize=14)
plt.xticks(fontsize=12)
plt.yticks(fontsize=12)
plt.grid(True, linestyle='--', alpha=0.7)
plt.legend(fontsize=12)

# Cross Alignment (CA) Loss
plt.subplot(2, 3, 3)
plt.plot(train_losses['ca_loss'], label='Train CA Loss', color='purple', linewidth=2)
plt.plot(val_losses['ca_loss'], label='Val CA Loss', color='brown', linewidth=2)
plt.title('Cross Alignment (CA) Loss Over Epochs', fontsize=16)
plt.xlabel('Epoch', fontsize=14)
plt.ylabel('Loss Value', fontsize=14)
plt.xticks(fontsize=12)
plt.yticks(fontsize=12)
plt.grid(True, linestyle='--', alpha=0.7)
plt.legend(fontsize=12)

# Disentanglement (DA) Loss
plt.subplot(2, 3, 4)
plt.plot(train_losses['da_loss'], label='Train DA Loss', color='cyan', linewidth=2)
plt.plot(val_losses['da_loss'], label='Val DA Loss', color='magenta', linewidth=2)
plt.title('Disentanglement (DA) Loss Over Epochs', fontsize=16)
plt.xlabel('Epoch', fontsize=14)
plt.ylabel('Loss Value', fontsize=14)
plt.xticks(fontsize=12)
plt.yticks(fontsize=12)
plt.grid(True, linestyle='--', alpha=0.7)
plt.legend(fontsize=12)

# Vector Quantization VAE (VQ-VAE) Loss
plt.subplot(2, 3, 5)
plt.plot(train_losses['vq_vae_loss'], label='Train VQ-VAE Loss', color='darkblue', linewidth=2)
plt.plot(val_losses['vq_vae_loss'], label='Val VQ-VAE Loss', color='darkorange', linewidth=2)
plt.title('Vector Quantization VAE (VQ-VAE) Loss Over Epochs', fontsize=16)
plt.xlabel('Epoch', fontsize=14)
plt.ylabel('Loss Value', fontsize=14)
plt.xticks(fontsize=12)
plt.yticks(fontsize=12)
plt.grid(True, linestyle='--', alpha=0.7)
plt.legend(fontsize=12)

# Ensuring no overlap and adding a main title
plt.suptitle("Individual Loss Functions Over Training and Validation Epochs", fontsize=20)
plt.tight_layout(rect=[0, 0, 1, 0.95])
plt.show()

# Setting a larger figure size
plt.figure(figsize=(18, 10))

# Training and Validation Total Loss
plt.subplot(2, 2, 1)
plt.plot(train_losses['total_loss'], label='Train Total Loss', color='blue', linewidth=2)
plt.plot(val_losses['total_loss'], label='Val Total Loss', color='orange', linewidth=2)
plt.title('Training and Validation Total Loss', fontsize=16)
plt.xlabel('Epoch', fontsize=14)
plt.ylabel('Loss Value', fontsize=14)
plt.xticks(fontsize=12)
plt.yticks(fontsize=12)
plt.grid(True, linestyle='--', alpha=0.7)
plt.legend(fontsize=12)
plt.tight_layout()

import matplotlib.pyplot as plt
from sklearn.manifold import TSNE


# Visualize latent space using t-SNE
def visualize_latent_space(model, dataloader):
    model.eval()
    all_latent = []
    all_labels = []

    with torch.no_grad():
        for data, target in dataloader:
            data = data.to(device)
            semantic_embeddings = get_semantic_embedding(target.cpu().numpy(), word_vectors).to(device)
            _, _, _, _, _, _, z_e, _, _ = model(data, semantic_embeddings)
            all_latent.append(z_e.cpu())
            all_labels.append(target.cpu())

    all_latent = torch.cat(all_latent, dim=0).numpy()
    all_labels = torch.cat(all_labels, dim=0).numpy()

    tsne = TSNE(n_components=2)
    latent_2d = tsne.fit_transform(all_latent)

    plt.figure(figsize=(10, 8))
    scatter = plt.scatter(latent_2d[:, 0], latent_2d[:, 1], c=all_labels, cmap='tab10', alpha=0.5)
    plt.colorbar(scatter, ticks=range(10), label='CIFAR-10 Classes')
    plt.title('t-SNE visualization of the latent space')
    plt.xlabel('Latent Dimension 1')
    plt.ylabel('Latent Dimension 2')
    plt.show()

# Visualize the latent space after training
visualize_latent_space(model, train_loader)

import numpy as np
import cv2
def sharpen_image(image):
    kernel = np.array([[0, -1, 0], [-1, 5,-1], [0, -1, 0]])
    sharpened = cv2.filter2D(image, -1, kernel)
    return np.clip(sharpened, 0, 1)  # Ensure values are in range

import numpy as np
import torch
import matplotlib.pyplot as plt

def generate_images_from_semantic_embeddings_fashionMnist(model, word_vectors, device, classes):
    model.eval()  # Set the model to evaluation mode

    generated_images = []

    for cls in classes:
        # Get the semantic embedding for the class
        embedding = word_vectors[cls]

        # Convert embedding to tensor and move to device
        embedding_tensor = torch.tensor(embedding).unsqueeze(0).to(device)  # Add batch dimension

        with torch.no_grad():
            # Forward pass through the semantic encoder
            mu_c, logvar_c, z_q, z_e, quantization_loss, commitment_loss = model.semantic_encoder(embedding_tensor)

            # Reparameterize the latent space using mu_c and logvar_c (if needed)
            latent_c = model.reparameterize(mu_c, logvar_c)

            # Decode the latent representation to generate the image
            generated_image = model.image_decoder(latent_c)

        # Reshape and clip/store the generated image
        generated_image = generated_image.view(28, 28).cpu().numpy()  # Reshape to (28, 28)
        # Normalize the image values to [0, 1] range if they are in float
        generated_image = np.clip(generated_image, 0, 1)  # Ensure the values are in [0, 1]

        generated_images.append(generated_image)

    return generated_images


# Function to plot the generated images
def plot_generated_images_fashionmnist(generated_images, class_names):
    fig, axes = plt.subplots(2, 5, figsize=(15, 6))
    axes = axes.flatten()

    for i, ax in enumerate(axes):
        ax.imshow(generated_images[i], cmap='gray')
        ax.set_title(f'Generated: {class_names[i]}')
        ax.axis('off')  # Turn off axis labels

    plt.tight_layout()
    plt.show()

# Assuming you have a list of fashion_mnist_classes
# Generate images using semantic embeddings
generated_images = generate_images_from_semantic_embeddings_fashionMnist(model, word_vectors, device, fashion_mnist_classes)

# Plot the generated images
plot_generated_images_fashionmnist(generated_images, fashion_mnist_classes)

import numpy as np
import matplotlib.pyplot as plt

# Function to visualize the generated image
def visualize_generated_image(generated_image):
    # Print the shape of the generated image for debugging
    print("Generated image shape:", generated_image.shape)

    # If the image is already 2D (grayscale), no need to transpose
    # Rescale the pixel values to [0, 1]
    generated_image = np.clip(generated_image, 0, 1)  # Ensure the values are in [0, 1]

    # Display the image
    plt.imshow(generated_image, cmap='gray')  # Use 'gray' colormap for grayscale images
    plt.axis('off')  # Hide axes
    plt.title('Generated Image')
    plt.show()

# Generate images using semantic embeddings
generated_images = generate_images_from_semantic_embeddings_fashionMnist(model, word_vectors, device, fashion_mnist_classes)

# Visualize the first generated image (assuming it's an image from fashion_mnist_classes)
visualize_generated_image(generated_images[2])